"""Step 4: evaluate the answers on evals/testset.yaml with deterministic scorers (no LLM in the scoring).

Every question is retrieved once and answered EVAL_RUNS times (the model is not deterministic), each answer is scored,
and the results are written to evals/results/answers/<tag>/:
  answers.jsonl     every answer with its scores (the input of the LLM judge)
  results.json      aggregates
  results.md        tables
  per_question.md   per question: the expected answer, the answers of every run, what failed
"""

import json
import random
import re
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from . import config as C
from .answer import answer, make_client, retrieve
from .language import detect
from .retrieve import Filters

SOURCE_ID = re.compile(r"\[?\bS\d{1,2}\b\]?")


# ---------------------------------------------------------------- test set

def load_testset(path: Path = C.TESTSET) -> list[dict]:
    questions = yaml.safe_load(path.read_text(encoding="utf-8"))["questions"]
    ids = [q["id"] for q in questions]
    if len(ids) != len(set(ids)):
        raise SystemExit("duplicate question ids in the test set")
    for q in questions:
        for key in ("question", "language", "type", "expect", "expected_answer", "must_include",
                    "must_not_include", "expected_sources"):
            if key not in q:
                raise SystemExit(f"{q['id']}: missing field {key}")
        if q["expect"] not in ("answer", "not_found"):
            raise SystemExit(f"{q['id']}: expect must be answer or not_found")
    return questions


def answer_language(q: dict) -> str:
    """The language the answer must be in: the question's, a mixed question counts as its dominant language."""
    # Not question_language(): that is the system under test (and changes with QUESTION_LANGUAGE). A mixed question
    # is answered in the language of its script: Cyrillic -> Ukrainian.
    if q["language"] != "mixed":
        return q["language"]
    letters = [c for c in q["question"] if c.isalpha()]
    return "uk" if sum("Ѐ" <= c <= "ӿ" for c in letters) > len(letters) / 3 else "en"


# ---------------------------------------------------------------- scorers

def normalize(text: str) -> str:
    """Lower case, one space, digits grouped without spaces ("3 000" -> "3000"), decimal comma -> point."""
    text = text.lower().replace(" ", " ").replace(" ", " ")
    text = re.sub(r"(?<=\d) (?=\d{3}\b)", "", text)
    text = re.sub(r"(?<=\d),(?=\d)", ".", text)
    return re.sub(r"\s+", " ", text)


def has_fact(text: str, item: str) -> bool:
    """`item` is one fact; "a | b" means any of the alternatives."""
    norm = normalize(text)
    return any(normalize(alt.strip()) in norm for alt in item.split("|") if alt.strip())


def claims_text(rec: dict) -> str:
    """What the answer states: the claims only (not the source list, whose section titles contain numbers)."""
    return "\n".join(c["text"] for c in rec["claims"])


def score(q: dict, rec: dict) -> dict:
    answered = rec["status"] == "answered"
    expected = q["expect"] == "answer"
    s = {"decision": answered == expected,
         "false_not_found": expected and not answered,        # should have answered
         "answered_unanswerable": answered and not expected}  # answered a question the documents do not answer
    lang = answer_language(q)
    if answered:
        text = claims_text(rec)
        detected = detect(text)
        s["language"] = detected == lang if detected else rec["language"] == lang
    else:
        s["language"] = rec["language"] == lang                # the "I don't know" text is in the question's language
    if answered and expected:
        text = claims_text(rec)
        s["facts"] = all(has_fact(text, item) for item in q["must_include"])
        s["facts_missing"] = [item for item in q["must_include"] if not has_fact(text, item)]
        s["traps"] = [item for item in q["must_not_include"] if has_fact(text, item)]
        cited = [cit["chunk_id"].split("#")[0] for c in rec["claims"] for cit in c["citations"]]
        if q["expected_sources"]:
            s["source_hit"] = any(d in q["expected_sources"] for d in cited)
            s["source_precision"] = sum(d in q["expected_sources"] for d in cited) / len(cited) if cited else 0.0
        s["id_leak"] = bool(SOURCE_ID.search(rec["text"].split("\n\n")[0] + " " + rec.get("missing", "")))
    if q["expected_sources"]:
        s["retrieval_hit"] = any(c["chunk_id"].split("#")[0] in q["expected_sources"] for c in rec["context"])
    # one verdict per answer
    if expected:
        s["pass"] = (answered and s["facts"] and not s["traps"] and s.get("source_hit", True)
                     and s["language"] and not s["id_leak"])
    else:
        s["pass"] = not answered and s["language"]
    return s


# ---------------------------------------------------------------- running

class InjectingRetriever:
    """Adds a planted chunk at rank 1 to the real hits (prompt injection through a document). The corpus and the
    index are not touched: the chunk exists only for this question in this run."""

    def __init__(self, retriever):
        self.retriever = retriever

    def search(self, query, mode="rerank", filters=None, k=C.TOP_K, inject=None, **kw):
        hits = self.retriever.search(query, mode=mode, filters=filters, k=k, **kw)
        if inject:
            top = hits[0]["score"] if hits else 0.0
            planted = {"status": "current", "language": "uk", "topic": "returns", "url": None,
                       **inject, "score": top + 1.0}
            hits = [planted] + hits[:k - 1]
            for i, h in enumerate(hits):
                h["rank"] = i + 1
        return hits


def run(runs: int = C.EVAL_RUNS, prompt_version: str = C.PROMPT_VERSION, ids: list[str] | None = None,
        tag: str | None = None, workers: int = C.EVAL_WORKERS, retriever=None, client=None,
        write: bool = True) -> dict:
    questions = [q for q in load_testset() if not ids or q["id"] in ids]
    if retriever is None:
        from .retrieve import Retriever
        retriever = Retriever.build(C.CHUNKS, "structured")
    client = client or make_client()
    injector = InjectingRetriever(retriever)
    started = time.perf_counter()

    # 1. Retrieval once per question (deterministic, CPU-bound: the reranker).
    got = {}
    for q in questions:
        got[q["id"]] = retrieve(q["question"], injector, client, Filters(status="current"), inject=q.get("inject"))
    print(f"retrieval: {len(questions)} questions in {time.perf_counter() - started:.0f} s")

    # 2. Answers: runs x questions, in parallel (the model calls dominate the time).
    jobs = [(q, r) for r in range(1, runs + 1) for q in questions]

    def one(job):
        q, r = job
        g = got[q["id"]]
        res = answer(q["question"], retriever, client=client, prompt_version=prompt_version, hits=g["hits"],
                     translations=g["translations"], retrieval_cost=g["cost_usd"])
        rec = res.to_dict()
        rec.update({"id": q["id"], "run": r})
        rec["scores"] = score(q, rec)
        return rec

    with ThreadPoolExecutor(max_workers=workers) as pool:
        records = list(pool.map(one, jobs))
    records.sort(key=lambda rec: (rec["id"], rec["run"]))
    elapsed = time.perf_counter() - started

    summary = aggregate(questions, records, runs)
    summary.update({"prompt_version": prompt_version, "model": C.ANSWER_MODEL, "effort": C.ANSWER_EFFORT,
                    "runs": runs, "questions": len(questions), "seconds": round(elapsed), "pipeline": pipeline()})
    print_summary(summary)
    if write:
        out = free_path(C.ANSWER_RESULTS / (tag or prompt_version))
        write_run(out, questions, records, summary)
    return summary


# ---------------------------------------------------------------- aggregation

def mean(values) -> float | None:
    values = [float(v) for v in values]
    return round(statistics.fmean(values), 3) if values else None


def percentile(values, p) -> int:
    values = sorted(values)
    return int(values[min(len(values) - 1, int(round(p * (len(values) - 1))))]) if values else 0


def bootstrap_ci(by_question: dict[str, list[float]], n: int = 2000, seed: int = 0) -> list[float] | None:
    """95% interval of the mean over all answers, resampling questions (the runs of one question are not
    independent, so questions, not answers, are the unit)."""
    groups = [v for v in by_question.values() if v]
    if not groups:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(n):
        sample = [rng.choice(groups) for _ in groups]
        values = [x for g in sample for x in g]
        means.append(sum(values) / len(values))
    means.sort()
    return [round(means[int(0.025 * n)], 3), round(means[int(0.975 * n) - 1], 3)]


def ci_by_question(records: list[dict], key, include=lambda r: True) -> list[float] | None:
    by_q = {}
    for r in records:
        if include(r):
            by_q.setdefault(r["id"], []).append(float(key(r)))
    return bootstrap_ci(by_q)


def aggregate(questions: list[dict], records: list[dict], runs: int) -> dict:
    qmap = {q["id"]: q for q in questions}
    by_q = {q["id"]: [r for r in records if r["id"] == q["id"]] for q in questions}
    expect_answer = [r for r in records if qmap[r["id"]]["expect"] == "answer"]
    answered_expected = [r for r in records if "facts" in r["scores"]]
    unanswerable = [r for r in records if qmap[r["id"]]["expect"] == "not_found"]
    with_sources = [r for r in answered_expected if "source_hit" in r["scores"]]
    called = [r for r in records if r["input_tokens"]]
    s = {
        "pass": mean(r["scores"]["pass"] for r in records),
        "decision": mean(r["scores"]["decision"] for r in records),
        "false_not_found": mean(r["scores"]["false_not_found"] for r in expect_answer),
        "answered_unanswerable": mean(r["scores"]["answered_unanswerable"] for r in unanswerable),
        "facts": mean(r["scores"]["facts"] for r in answered_expected),
        "traps": mean(bool(r["scores"]["traps"]) for r in answered_expected),
        "source_hit": mean(r["scores"]["source_hit"] for r in with_sources),
        "source_precision": mean(r["scores"]["source_precision"] for r in with_sources),
        "retrieval_hit": mean(r["scores"]["retrieval_hit"] for r in records if "retrieval_hit" in r["scores"]),
        "language": mean(r["scores"]["language"] for r in records),
        "id_leak": mean(r["scores"]["id_leak"] for r in answered_expected),
        "dropped_claims": sum(len(r["dropped"]) for r in records),
        "status": {st: sum(r["status"] == st for r in records) for st in sorted({r["status"] for r in records})},
        # not mean(): it rounds to 3 decimals, and a question costs about $0.0005
        "cost_per_1000": round(statistics.fmean(r["cost_usd"] for r in records) * 1000, 3),
        "cost_per_1000_answered": round(statistics.fmean(r["cost_usd"] for r in called) * 1000, 3) if called else 0.0,
        "latency_ms_p50": percentile([r["latency_ms"] for r in called], 0.5),
        "latency_ms_p95": percentile([r["latency_ms"] for r in called], 0.95),
        "input_tokens_avg": round(mean(r["input_tokens"] for r in called)) if called else 0,
        "output_tokens_avg": round(mean(r["output_tokens"] for r in called)) if called else 0,
        "total_cost_usd": round(sum(r["cost_usd"] for r in records), 4),
    }
    s["ci95"] = {
        "pass": ci_by_question(records, lambda r: r["scores"]["pass"]),
        "decision": ci_by_question(records, lambda r: r["scores"]["decision"]),
        "false_not_found": ci_by_question(records, lambda r: r["scores"]["false_not_found"],
                                          lambda r: qmap[r["id"]]["expect"] == "answer"),
    }
    s["by_type"] = {}
    for t in sorted({q["type"] for q in questions}):
        recs = [r for r in records if qmap[r["id"]]["type"] == t]
        s["by_type"][t] = {"questions": sum(q["type"] == t for q in questions), "pass": mean(r["scores"]["pass"] for r in recs)}
    s["by_language"] = {}
    for lang in sorted({q["language"] for q in questions}):
        recs = [r for r in records if qmap[r["id"]]["language"] == lang]
        s["by_language"][lang] = {"questions": sum(q["language"] == lang for q in questions),
                                  "pass": mean(r["scores"]["pass"] for r in recs)}
    s["per_question"] = {qid: {"passed_runs": sum(r["scores"]["pass"] for r in recs), "runs": len(recs),
                               "statuses": [r["status"] for r in recs]}
                         for qid, recs in by_q.items()}
    s["always_pass"] = sum(v["passed_runs"] == v["runs"] for v in s["per_question"].values())
    s["unstable"] = [qid for qid, v in s["per_question"].items() if 0 < v["passed_runs"] < v["runs"]]
    s["always_fail"] = [qid for qid, v in s["per_question"].items() if v["passed_runs"] == 0]
    return s


# ---------------------------------------------------------------- reports

METRICS = [
    ("pass", "answer passes all deterministic checks"),
    ("decision", "answered when it should, said \"I don't know\" when it should"),
    ("false_not_found", "\"I don't know\" although the documents answer it (of answerable questions)"),
    ("answered_unanswerable", "answered a question the documents do not answer"),
    ("facts", "all key facts present (of answered, answerable questions)"),
    ("traps", "a trap value in the answer"),
    ("source_hit", "at least one citation from an expected document"),
    ("source_precision", "share of citations from expected documents"),
    ("retrieval_hit", "an expected document is in the context"),
    ("language", "answer in the language of the question"),
    ("id_leak", "a source id like S1 shown to the customer"),
]


def print_summary(s: dict) -> None:
    print(f"\n{s.get('questions')} questions x {s.get('runs')} runs, prompt {s.get('prompt_version')}")
    for key, label in METRICS:
        print(f"  {key:<22} {s[key] if s[key] is not None else '-':<7} {label}")
    print(f"  95% intervals (bootstrap over questions): {s.get('ci95')}")
    print(f"  statuses {s['status']}")
    print(f"  always pass {s['always_pass']}, unstable {s['unstable']}, always fail {s['always_fail']}")
    print(f"  cost ${s['cost_per_1000']}/1000 questions (${s['cost_per_1000_answered']}/1000 that reach the model), "
          f"latency p50 {s['latency_ms_p50']} ms, p95 {s['latency_ms_p95']} ms, total ${s['total_cost_usd']}")


def fmt(v) -> str:
    return "-" if v is None else f"{v:.2f}" if isinstance(v, float) else str(v)


def to_markdown(s: dict) -> str:
    lines = [f"# Answer evaluation: prompt {s['prompt_version']}\n",
             f"{s['questions']} questions x {s['runs']} runs, {s['model']} (effort {s['effort']}). "
             "Deterministic scorers only; per question details: [per_question.md](per_question.md).\n",
             f"Pipeline: `{s.get('pipeline', '-')}`\n",
             "| metric | value | meaning |", "|---|---|---|"]
    ci = s.get("ci95", {})
    lines += [f"| {k} | {fmt(s[k])}{f' [{ci[k][0]:.2f}–{ci[k][1]:.2f}]' if ci.get(k) else ''} | {label} |"
              for k, label in METRICS]
    lines += ["\n[a–b]: 95% interval, bootstrap over questions."]
    lines += ["\n| type | questions | pass |", "|---|---|---|"]
    lines += [f"| {t} | {v['questions']} | {fmt(v['pass'])} |" for t, v in s["by_type"].items()]
    lines += ["\n| language | questions | pass |", "|---|---|---|"]
    lines += [f"| {t} | {v['questions']} | {fmt(v['pass'])} |" for t, v in s["by_language"].items()]
    lines += ["\n## Stability across runs\n",
              f"- passed in every run: {s['always_pass']} of {s['questions']}",
              f"- unstable (passed in some runs): {', '.join(s['unstable']) or '-'}",
              f"- failed in every run: {', '.join(s['always_fail']) or '-'}",
              f"- statuses: {s['status']}; claims dropped by the citation check: {s['dropped_claims']}",
              "\n## Cost and latency\n",
              f"- ${s['cost_per_1000']} per 1,000 questions (${s['cost_per_1000_answered']} per 1,000 that reach the model; "
              "the others stop at the retrieval threshold and cost nothing)",
              f"- tokens per model call: {s['input_tokens_avg']} in, {s['output_tokens_avg']} out (thinking included)",
              f"- latency per question that reaches the model: p50 {s['latency_ms_p50']} ms, p95 {s['latency_ms_p95']} ms",
              f"- this evaluation: ${s['total_cost_usd']}, {s['seconds']} s"]
    return "\n".join(lines) + "\n"


def per_question_md(questions: list[dict], records: list[dict], s: dict) -> str:
    out = [f"# Answers per question: prompt {s['prompt_version']}\n"]
    for q in questions:
        recs = [r for r in records if r["id"] == q["id"]]
        pq = s["per_question"][q["id"]]
        out.append(f"## {q['id']} ({q['language']}, {q['type']}, expect {q['expect']}): "
                   f"{pq['passed_runs']}/{pq['runs']} passed\n")
        out.append(f"**Q:** {q['question']}  \n**Expected:** {q['expected_answer']}\n")
        if q.get("known_issue"):
            out.append(f"*Known issue:* {q['known_issue']}\n")
        for r in recs:
            sc = r["scores"]
            fails = [k for k in ("decision", "facts", "language") if sc.get(k) is False]
            fails += [f"trap {t}" for t in sc.get("traps", [])] + (["source"] if sc.get("source_hit") is False else []) \
                + (["id leak"] if sc.get("id_leak") else [])
            mark = "✅" if sc["pass"] else "❌ " + ", ".join(fails)
            out.append(f"**Run {r['run']}** — {r['status']}, top score {fmt(r['top_score'])}, {mark}\n")
            out.append("> " + r["text"].replace("\n", "  \n> ") + "\n")
        ctx = recs[0]["context"]
        out.append("Context: " + ", ".join(f"`{c['chunk_id']}` ({c['score']})" for c in ctx) + "\n")
    return "\n".join(out)


def rescore(tag: str = C.PROMPT_VERSION, out_tag: str | None = None) -> dict:
    """Score the saved answers of `tag` again (after a change to the test set or the scorers) without calling the
    model. The source run is left as it is: the new scores go to a new folder next to it."""
    folder = C.ANSWER_RESULTS / tag
    out = free_path(C.ANSWER_RESULTS / (out_tag or f"{tag}-rescored"))
    records = [json.loads(l) for l in (folder / "answers.jsonl").read_text(encoding="utf-8").splitlines()]
    questions = [q for q in load_testset() if q["id"] in {r["id"] for r in records}]
    qmap = {q["id"]: q for q in questions}
    for r in records:
        r["scores"] = score(qmap[r["id"]], r)
    old = json.loads((folder / "results.json").read_text(encoding="utf-8"))
    runs = max(r["run"] for r in records)
    summary = aggregate(questions, records, runs)
    summary.update({k: old[k] for k in ("prompt_version", "model", "effort", "seconds") if k in old})
    summary.update({"runs": runs, "questions": len(questions), "rescored_from": tag})
    print_summary(summary)
    write_run(out, questions, records, summary)
    return summary


def free_path(path: Path) -> Path:
    """`path` if it does not exist yet, otherwise path_2, path_3, ...: a run never overwrites an earlier one."""
    if not path.exists():
        return path
    k = 2
    while (candidate := path.with_name(f"{path.stem}_{k}{path.suffix}")).exists():
        k += 1
    return candidate


def write_run(out: Path, questions: list[dict], records: list[dict], summary: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "answers.jsonl", "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    (out / "results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "results.md").write_text(to_markdown(summary), encoding="utf-8")
    (out / "per_question.md").write_text(per_question_md(questions, records, summary), encoding="utf-8")
    print(f"written to {out}")


def free_stem(folder: Path, name: str, suffixes: tuple[str, ...]) -> Path:
    """folder/name, or folder/name_2, name_3 ...: the first stem for which none of the files exists yet, so a group of
    files of one run (.json + .jsonl, .json + .md) gets the same number and never overwrites an earlier run."""
    k, stem = 1, folder / name
    while any(stem.with_name(stem.name + s).exists() for s in suffixes):
        k += 1
        stem = folder / f"{name}_{k}"
    return stem


def pipeline() -> dict:
    """The switches an evaluation ran with, so every result can be traced to its configuration."""
    import hashlib
    return {"question_language": C.QUESTION_LANGUAGE, "faq_chunks": C.FAQ_CHUNKS,
            "query_translation": C.QUERY_TRANSLATION, "context_min_score": C.CONTEXT_MIN_SCORE,
            "demote_outdated_faq": C.DEMOTE_OUTDATED_FAQ,
            "min_rerank_score": C.MIN_RERANK_SCORE, "context_budget": C.CONTEXT_BUDGET,
            "chunks": hashlib.sha256(C.CHUNKS.read_bytes()).hexdigest()[:12]}

