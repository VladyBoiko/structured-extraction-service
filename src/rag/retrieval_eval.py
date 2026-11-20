"""Retrieval quality: recall@k and MRR on evals/retrieval_questions.yaml.

Experiments (all on the same questions):
  models    vector search with each embedding model (structure-aware chunks)
  modes     vector / BM25 / hybrid / hybrid + rerank, for structure-aware and fixed-size chunks
  filters   the version-trap questions with and without the default status=current filter
Writes evals/results/retrieval/{results.json, results.md, per_question.md}.
"""

import hashlib
import json
from pathlib import Path

import yaml

from . import config as C
from .retrieve import MODES, NO_FILTER, Filters, Retriever, Timer, load_chunks

EVAL_DEPTH = 10   # ranks are looked up to 10; recall@5 and MRR@10 are reported


def norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def load_questions(path: Path = C.RETRIEVAL_QUESTIONS) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def questions_hash(questions: list[dict]) -> str:
    return hashlib.sha256(json.dumps(questions, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def is_hit(chunk: dict, question: dict) -> bool:
    return any(chunk["doc_id"] == e["doc"] and norm(e["quote"]) in norm(chunk["text"]) for e in question["evidence"])


def gold_chunks(question: dict, chunks: list[dict]) -> list[str]:
    return [c["chunk_id"] for c in chunks if is_hit(c, question)]


def lint(questions: list[dict], chunks: list[dict]) -> list[str]:
    """Every evidence quote must exist in its document, or the question can never be answered."""
    problems = []
    docs = {c["doc_id"] for c in chunks}
    for q in questions:
        for e in q["evidence"]:
            if e["doc"] not in docs:
                problems.append(f"{q['id']}: document {e['doc']} is not in the chunks")
            elif not any(c["doc_id"] == e["doc"] and norm(e["quote"]) in norm(c["text"]) for c in chunks):
                problems.append(f"{q['id']}: quote not found in {e['doc']}: {e['quote']!r}")
    return problems


def run_config(retriever: Retriever, questions: list[dict], mode: str, filters: Filters | None = None,
               translations: dict[str, dict] | None = None) -> dict:
    per_q, timer = {}, Timer()
    for q in questions:
        kw = {"translations": translations[q["id"]]} if translations and translations.get(q["id"]) else {}
        with timer:
            hits = retriever.search(q["question"], mode=mode, filters=filters, k=EVAL_DEPTH, **kw)
        rank = next((h["rank"] for h in hits if is_hit(h, q)), None)
        superseded = [h["chunk_id"] for h in hits[:C.TOP_K] if h["doc_id"] in q.get("superseded", [])]
        per_q[q["id"]] = {"rank": rank, "top": [h["chunk_id"] for h in hits[:C.TOP_K]], "superseded_top5": superseded}
    ranks = [v["rank"] for v in per_q.values()]
    n = len(ranks)
    return {
        "hit@1": round(sum(r == 1 for r in ranks if r) / n, 3),
        "recall@5": round(sum(1 for r in ranks if r and r <= C.TOP_K) / n, 3),
        "mrr@10": round(sum(1 / r for r in ranks if r) / n, 3),
        "ms": round(timer.ms),
        "misses@5": [qid for qid, v in per_q.items() if not v["rank"] or v["rank"] > C.TOP_K],
        "per_question": per_q,
    }


SIZE_SWEEP = [(300, 40), (300, 150), (380, 150)]   # (max tokens, merge siblings below) for structure-aware chunks


def run_sweep(questions: list[dict]) -> dict:
    """Structure-aware chunking with other sizes: does merging small sections more help retrieval?
    380 is the largest budget that still fits the e5 window (512 XLM-R tokens, measured: up to 1.3x o200k)."""
    from .ingest import structured_variant
    out = {}
    for max_t, min_t in SIZE_SWEEP:
        chunks = structured_variant(max_t, min_t)
        r = Retriever(chunks, f"sweep_{max_t}_{min_t}")
        for mode in ("vector", "hybrid", "rerank"):
            res = run_config(r, questions, mode)
            res["chunks"] = len(chunks)
            res["avg_tokens"] = round(sum(c["n_tokens"] for c in chunks) / len(chunks))
            out[f"{max_t}/{min_t}/{mode}"] = res
            print(f"structured max {max_t} merge<{min_t} ({len(chunks)} chunks) {mode:<7} hit@1 {res['hit@1']:.2f}  "
                  f"recall@5 {res['recall@5']:.2f}  MRR {res['mrr@10']:.2f}  misses {' '.join(res['misses@5']) or '-'}")
    return out


RERANKER_SWEEP = [("bge-m3", 20), ("bge-m3", 10), ("jina", 20), ("msmarco", 20)]


def run_rerankers(questions: list[dict], chunks: list[dict]) -> dict:
    """Cross-encoders and candidate counts: quality vs. latency (the reranker is the slow step)."""
    out = {}
    original = C.RERANK_CANDIDATES
    try:
        for key, n in RERANKER_SWEEP:
            C.RERANK_CANDIDATES = n
            r = Retriever(chunks, "structured", rerank_key=key)
            res = run_config(r, questions, "rerank")
            out[f"{key}/{n}"] = res
            print(f"reranker {key:<8} candidates {n:>2}: hit@1 {res['hit@1']:.2f}  recall@5 {res['recall@5']:.2f}  "
                  f"MRR {res['mrr@10']:.2f}  {res['ms']:>5} ms  misses {' '.join(res['misses@5']) or '-'}")
    finally:
        C.RERANK_CANDIDATES = original
    return out


def run(models: list[str] | None = None, write: bool = True, sweep: bool = False, tag: str | None = None) -> dict:
    data = load_questions()
    questions = data["questions"]
    structured, fixed = load_chunks(C.CHUNKS), load_chunks(C.CHUNKS_FIXED)
    problems = lint(questions, structured)
    if problems:
        raise SystemExit("retrieval questions do not match the corpus:\n  " + "\n  ".join(problems))
    results = {"questions": len(questions), "k": C.TOP_K,
               "embed_model": C.EMBED_MODEL, "rerank_model": C.RERANK_MODEL, "models": {}, "modes": {}, "filters": {}}

    # 1. Embedding models, vector search only.
    for key in models or [C.EMBED_MODEL]:
        r = Retriever(structured, "structured", model_key=key)
        print(f"model {key}: index {'built' if r.built_now else 'reused'}, embedded {r.embedder.last_computed}")
        results["models"][key] = run_config(r, questions, "vector")
        print(f"  vector recall@5 {results['models'][key]['recall@5']:.2f}  MRR {results['models'][key]['mrr@10']:.2f}")

    # 2. Search modes x chunking, with the chosen model.
    for name, chunks in (("structured", structured), ("fixed", fixed)):
        r = Retriever(chunks, name)
        for mode in MODES:
            res = run_config(r, questions, mode)
            results["modes"][f"{name}/{mode}"] = res
            print(f"{name:<10} {mode:<7} hit@1 {res['hit@1']:.2f}  recall@5 {res['recall@5']:.2f}  "
                  f"MRR {res['mrr@10']:.2f}  {res['ms']:>5} ms  misses {' '.join(res['misses@5']) or '-'}")

    # 2b. With QUERY_TRANSLATION on: the question in uk / en / de, each chunk reranked against its own language.
    if C.QUERY_TRANSLATION:
        from .answer import make_client, translate
        client = make_client()
        translations = {q["id"]: translate(client, q["question"])[0] for q in questions}
        res = run_config(Retriever(structured, "structured"), questions, "rerank", translations=translations)
        res["translations"] = translations
        results["modes"]["structured/rerank+translation"] = res
        print(f"structured rerank+translation hit@1 {res['hit@1']:.2f}  recall@5 {res['recall@5']:.2f}  "
              f"MRR {res['mrr@10']:.2f}  {res['ms']:>5} ms  misses {' '.join(res['misses@5']) or '-'}")

    # 3. Version traps: does an outdated policy reach the top-5 without the status filter?
    traps = [q for q in questions if q.get("superseded")]
    r = Retriever(structured, "structured")
    for label, flt in (("status=current (default)", None), ("no filter", NO_FILTER)):
        res = run_config(r, traps, "rerank", flt)
        res["superseded_in_top5"] = sum(len(v["superseded_top5"]) for v in res["per_question"].values())
        res["questions_with_superseded"] = [qid for qid, v in res["per_question"].items() if v["superseded_top5"]]
        results["filters"][label] = res
        print(f"traps, {label:<26} recall@5 {res['recall@5']:.2f}  outdated chunks in top-5: {res['superseded_in_top5']} "
              f"(questions {' '.join(res['questions_with_superseded']) or '-'})")

    # Experiments that take minutes (other models, the size sweep) are not re-run every time: keep the last
    # result of each, unless the questions changed (then the old numbers would not be comparable).
    previous_file = C.RETRIEVAL_RESULTS / "results.json"
    previous = json.loads(previous_file.read_text(encoding="utf-8")) if previous_file.exists() else {}
    chunks_hash = hashlib.sha256(C.CHUNKS.read_bytes()).hexdigest()[:12]
    same_questions = previous.get("questions_hash") == questions_hash(questions)
    same_chunks = same_questions and previous.get("chunks_hash") == chunks_hash
    if same_chunks:   # model results depend on the indexed chunks
        for key, value in previous.get("models", {}).items():
            results["models"].setdefault(key, value)
    if sweep:   # the sweep and the reranker comparison build their own chunks / use the current ones
        results["sweep"] = run_sweep(questions)
        results["rerankers"] = run_rerankers(questions, structured)
    else:
        if same_questions and "sweep" in previous:
            results["sweep"] = previous["sweep"]
        if same_chunks and "rerankers" in previous:
            results["rerankers"] = previous["rerankers"]
    results["questions_hash"] = questions_hash(questions)
    results["chunks_hash"] = chunks_hash

    results["pipeline"] = {"faq_chunks": C.FAQ_CHUNKS, "query_translation": C.QUERY_TRANSLATION}
    if write:   # a new run never overwrites an earlier one: the first run is in results/retrieval/, later ones in a
                # folder of their own next to it
        from .answer_eval import free_path
        out = C.RETRIEVAL_RESULTS
        if tag or (out / "results.json").exists():
            out = free_path(C.RETRIEVAL_RESULTS / (tag or "run"))
        out.mkdir(parents=True, exist_ok=True)
        (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (out / "results.md").write_text(to_markdown(results, questions), encoding="utf-8")
        write_per_question(questions, structured, r, folder=out)
        print(f"written to {out}")
    return results


# ---------------------------------------------------------------- reports

def to_markdown(res: dict, questions: list[dict]) -> str:
    lines = [f"# Retrieval results\n",
             f"{res['questions']} questions, recall@{res['k']} and MRR@10. Gold = evidence quote in the retrieved chunk. "
             "Per question gold and top-5: [per_question.md](per_question.md).\n",
             "## Embedding models (vector search, structure-aware chunks)\n",
             "| model | hit@1 | recall@5 | MRR@10 | ms/query | misses@5 |", "|---|---|---|---|---|---|"]
    for key, r in res["models"].items():
        lines.append(f"| {key} | {r['hit@1']:.2f} | {r['recall@5']:.2f} | {r['mrr@10']:.2f} | {r['ms']} | {' '.join(r['misses@5']) or '-'} |")
    lines += [f"\n## Search modes x chunking (embeddings: {res['embed_model']}, reranker: {res['rerank_model']})\n",
              "| chunks | mode | hit@1 | recall@5 | MRR@10 | ms/query | misses@5 |", "|---|---|---|---|---|---|---|"]
    for key, r in res["modes"].items():
        chunks, mode = key.split("/")
        lines.append(f"| {chunks} | {mode} | {r['hit@1']:.2f} | {r['recall@5']:.2f} | {r['mrr@10']:.2f} | {r['ms']} | "
                     f"{' '.join(r['misses@5']) or '-'} |")
    if res.get("sweep"):
        lines += ["\n## Structure-aware chunk size sweep\n",
                  "| max tokens | merge siblings below | chunks | avg tokens | mode | hit@1 | recall@5 | MRR@10 | misses@5 |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for key, r in res["sweep"].items():
            max_t, min_t, mode = key.split("/")
            lines.append(f"| {max_t} | {min_t} | {r['chunks']} | {r['avg_tokens']} | {mode} | {r['hit@1']:.2f} | "
                         f"{r['recall@5']:.2f} | {r['mrr@10']:.2f} | {' '.join(r['misses@5']) or '-'} |")
    lines += ["\n## Version traps: the status filter (hybrid + rerank)\n",
              "| filter | recall@5 | outdated chunks in top-5 | questions affected |", "|---|---|---|---|"]
    for label, r in res["filters"].items():
        lines.append(f"| {label} | {r['recall@5']:.2f} | {r['superseded_in_top5']} | {' '.join(r['questions_with_superseded']) or '-'} |")
    lines += ["\n## Rank of the first relevant chunk per question\n"]
    keys = list(res["modes"])
    lines.append("| question | " + " | ".join(keys) + " |")
    lines.append("|---|" + "---|" * len(keys))
    for q in questions:
        cells = [str(res["modes"][k]["per_question"][q["id"]]["rank"] or "–") for k in keys]
        lines.append(f"| {q['id']} {q['question'][:60]} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def write_per_question(questions: list[dict], chunks: list[dict], retriever: Retriever, folder=None) -> None:
    """Per question: the chunks its evidence points to and the top-5 of the chosen configuration."""
    by_id = {c["chunk_id"]: c for c in chunks}
    out = ["# Retrieval per question\n",
           "Generated by `python -m src.rag eval-retrieval`: the gold chunks of every question and the top-5 of the "
           "chosen configuration (hybrid + rerank, current documents only). ✅ = the chunk contains an evidence quote.\n"]
    for q in questions:
        out.append(f"## {q['id']} ({q['language']}): {q['question']}\n")
        if q.get("trap"):
            out.append(f"*Trap:* {q['trap']}\n")
        out.append("**Gold (chunks that contain an evidence quote):**\n")
        for cid in gold_chunks(q, chunks):
            c = by_id[cid]
            out.append(f"- `{cid}` — {c['section'][:110]}")
        out.append("\n**Evidence quotes:**\n")
        for e in q["evidence"]:
            out.append(f"- `{e['doc']}`: «{e['quote']}»")
        out.append("\n**Top-5 (hybrid + rerank, current documents only):**\n")
        for h in retriever.search(q["question"], mode="rerank"):
            mark = "✅" if is_hit(h, q) else "  "
            snippet = " ".join(h["text"].split())[:160]
            out.append(f"{h['rank']}. {mark} `{h['chunk_id']}` — {h['section'][:80]}  \n   _{snippet}_")
        out.append("")
    (folder or C.RETRIEVAL_RESULTS).joinpath("per_question.md").write_text("\n".join(out), encoding="utf-8")


def run_quick(tag: str = "ci") -> dict:
    """CI: only the configuration in use (structure-aware chunks, hybrid + rerank, with query translation when it is
    on), on the retrieval questions. Minutes instead of the full comparison of models, modes and sizes."""
    from .answer_eval import free_path
    data = load_questions()
    questions = data["questions"]
    structured = load_chunks(C.CHUNKS)
    problems = lint(questions, structured)
    if problems:
        raise SystemExit("retrieval questions do not match the corpus:\n  " + "\n  ".join(problems))
    r = Retriever(structured, "structured")
    translations = None
    key = "structured/rerank"
    if C.QUERY_TRANSLATION:
        from .answer import translate   # cached translations need no API key
        translations = {q["id"]: translate(None, q["question"])[0] for q in questions}
        key = "structured/rerank+translation"
    res = run_config(r, questions, "rerank", translations=translations)
    print(f"{key}: hit@1 {res['hit@1']:.2f}  recall@5 {res['recall@5']:.2f}  MRR {res['mrr@10']:.2f}  "
          f"{res['ms']} ms  misses {' '.join(res['misses@5']) or '-'}")
    results = {"questions": len(questions), "k": C.TOP_K, "quick": True, "modes": {key: res},
               "pipeline": {"faq_chunks": C.FAQ_CHUNKS, "query_translation": C.QUERY_TRANSLATION},
               "chunks_hash": hashlib.sha256(C.CHUNKS.read_bytes()).hexdigest()[:12]}
    out = free_path(C.RETRIEVAL_RESULTS / tag)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"written to {out}")
    return results
