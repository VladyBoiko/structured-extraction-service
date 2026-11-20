"""LLM judge (step 4): grades an answer against the reference answer as correct / partial / incorrect.

calibrate()  runs the judge on the answers a person labelled (evals/judge_calibration.yaml) and reports agreement and
             Cohen's kappa, so the judge's grades on the whole test set can be trusted (or not).
judge_run()  grades every answer of an evaluation run (evals/results/answers/<tag>/answers.jsonl).
"""

import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import yaml

from . import config as C
from .answer import cost, make_client

LABELS = ("correct", "partial", "incorrect")
SCHEMA = {
    "type": "object",
    "properties": {"reason": {"type": "string"}, "label": {"type": "string", "enum": list(LABELS)}},
    "required": ["reason", "label"],
    "additionalProperties": False,
}


def load_prompt(version: str = C.JUDGE_PROMPT_VERSION) -> str:
    return (C.JUDGE_PROMPTS_DIR / f"{version}.md").read_text(encoding="utf-8").strip()


def judge_one(client, question: str, expected: str, answer_text: str, prompt: str) -> dict:
    user = (f"<question>\n{question}\n</question>\n\n<reference_answer>\n{expected}\n</reference_answer>\n\n"
            f"<assistant_answer>\n{answer_text}\n</assistant_answer>")
    resp = client.messages.create(
        model=C.JUDGE_MODEL, max_tokens=4000,
        system=[{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}, "effort": C.JUDGE_EFFORT})
    if resp.stop_reason != "end_turn":
        return {"label": None, "reason": f"stop_reason={resp.stop_reason}", "cost_usd": 0.0}
    data = json.loads(next(b.text for b in resp.content if b.type == "text"))
    u = resp.usage
    data["cost_usd"] = cost(C.JUDGE_MODEL, u.input_tokens, u.output_tokens,
                            getattr(u, "cache_creation_input_tokens", 0) or 0,
                            getattr(u, "cache_read_input_tokens", 0) or 0)
    return data


# ---------------------------------------------------------------- agreement

def cohen_kappa(a: list[str], b: list[str]) -> float:
    """Agreement corrected for chance: (observed - expected) / (1 - expected)."""
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in set(a) | set(b)) / (n * n)
    return 1.0 if expected == 1 else round((observed - expected) / (1 - expected), 3)


def confusion(human: list[str], judge: list[str]) -> dict:
    return {h: {j: sum(1 for x, y in zip(human, judge) if x == h and y == j) for j in LABELS} for h in LABELS}


# ---------------------------------------------------------------- calibration

def calibrate(prompt_version: str = C.JUDGE_PROMPT_VERSION, repeats: int = 3, client=None, write: bool = True,
              labels_file=C.JUDGE_CALIBRATION, name: str = "calibration", answers_tag: str = "v1") -> dict:
    """The judge grades every labelled answer `repeats` times: agreement and kappa use the majority label, and the
    share of answers graded the same in every repeat shows how stable the judge is."""
    items = yaml.safe_load(labels_file.read_text(encoding="utf-8"))["answers"]
    missing = [i["id"] for i in items if i.get("human_label") not in LABELS]
    if missing:
        raise SystemExit(f"not labelled: {missing}")
    client = client or make_client()
    prompt = load_prompt(prompt_version)
    jobs = [i for _ in range(repeats) for i in items]
    with ThreadPoolExecutor(max_workers=C.EVAL_WORKERS) as pool:
        flat = list(pool.map(lambda i: judge_one(client, i["question"], i["expected_answer"], i["answer"], prompt), jobs))
    per_item = [[flat[r * len(items) + k] for r in range(repeats)] for k in range(len(items))]
    verdicts = []
    for vs in per_item:
        labels = [v["label"] for v in vs]
        majority = Counter(labels).most_common(1)[0][0]
        verdicts.append({"label": majority, "labels": labels,
                         "reason": next(v["reason"] for v in vs if v["label"] == majority),
                         "cost_usd": sum(v["cost_usd"] for v in vs)})
    human = [i["human_label"] for i in items]
    judge = [v["label"] for v in verdicts]
    rows = [{"id": i["id"], "run": i["run"], "human": i["human_label"], "judge": v["label"], "judge_runs": v["labels"],
             "agree": h == j, "human_note": i.get("human_note", ""), "judge_reason": v["reason"]}
            for i, v, h, j in zip(items, verdicts, human, judge)]
    stable = sum(len(set(v["labels"])) == 1 for v in verdicts) / len(items)
    per_repeat = [sum(vs[r]["label"] == i["human_label"] for vs, i in zip(per_item, items)) / len(items)
                  for r in range(repeats)]
    # The same answers through the deterministic scorers ("pass" counted as correct): what the judge adds.
    det = deterministic_agreement(items, answers_tag)
    res = {"judge_prompt": prompt_version, "labels_file": labels_file.name, "answers_tag": answers_tag,
           "model": C.JUDGE_MODEL, "effort": C.JUDGE_EFFORT, "n": len(items),
           "repeats": repeats, "agreement": round(sum(r["agree"] for r in rows) / len(rows), 3),
           "kappa": cohen_kappa(human, judge), "stable": round(stable, 3),
           "agreement_per_repeat": [round(a, 3) for a in per_repeat],
           "deterministic_agreement": det,
           "human_labels": dict(Counter(human)), "judge_labels": dict(Counter(judge)),
           "confusion": confusion(human, judge), "cost_usd": round(sum(v["cost_usd"] for v in verdicts), 5),
           "rows": rows}
    print(f"judge {prompt_version}: agreement {res['agreement']:.2f}, Cohen's kappa {res['kappa']:.2f} on {res['n']} "
          f"answers (majority of {repeats}); per repeat {res['agreement_per_repeat']}; same label in every repeat "
          f"{res['stable']:.2f}")
    for r in rows:
        if not r["agree"] or len(set(r["judge_runs"])) > 1:
            print(f"  {r['id']}: human {r['human']}, judge {r['judge_runs']}: {r['judge_reason']}")
    if write:
        from .answer_eval import free_stem
        C.JUDGE_RESULTS.mkdir(parents=True, exist_ok=True)
        stem = free_stem(C.JUDGE_RESULTS, f"{name}_{prompt_version}", (".json", ".md"))
        stem.with_name(stem.name + ".json").write_text(
            json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        stem.with_name(stem.name + ".md").write_text(calibration_md(res), encoding="utf-8")
        print(f"written to {stem}.json / .md")
    return res


def deterministic_agreement(items: list[dict], tag: str = "v1") -> dict | None:
    """Agreement of the deterministic verdict (pass = correct, fail = partial or incorrect) with the person, on the
    same answers. Needs the evaluation run the answers come from (evals/results/answers/v1/answers.jsonl)."""
    path = C.ANSWER_RESULTS / tag / "answers.jsonl"
    if not path.exists():
        return None
    recs = {(r["id"], r["run"]): r for r in map(json.loads, path.read_text(encoding="utf-8").splitlines())}
    pairs = [(i, recs.get((i["id"], i["run"]))) for i in items]
    pairs = [(i, r) for i, r in pairs if r]
    agree = [r["scores"]["pass"] == (i["human_label"] == "correct") for i, r in pairs]
    return {"n": len(pairs), "agreement": round(sum(agree) / len(pairs), 3),
            "disagree": [i["id"] for (i, _), a in zip(pairs, agree) if not a]}


def calibration_md(res: dict) -> str:
    lines = [f"# Judge calibration: judge prompt {res['judge_prompt']}\n",
             f"{res['n']} answers labelled by a person ([evals/judge_calibration.yaml](../../judge_calibration.yaml)) "
             f"and by the judge ({res['model']}, effort {res['effort']}).\n",
             f"The judge graded every answer {res['repeats']} times; agreement and kappa use its majority label.\n",
             f"- agreement: **{res['agreement']:.2f}** (per repeat: {', '.join(f'{a:.2f}' for a in res['agreement_per_repeat'])})",
             f"- Cohen's kappa: **{res['kappa']:.2f}**",
             f"- stability: the same label in all {res['repeats']} repeats for **{res['stable']:.2f}** of the answers",
             f"- human labels: {res['human_labels']}; judge labels: {res['judge_labels']}",
             f"- cost: ${res['cost_usd']}\n"]
    det = res.get("deterministic_agreement")
    if det:
        lines += [f"For comparison, the deterministic scorers on the same answers (pass counted as correct) agree with "
                  f"the person on **{det['agreement']:.2f}** ({det['n']} answers); they disagree on "
                  f"{', '.join(det['disagree'])}: a correct answer that mentions an outdated value fails the trap "
                  f"check, and a confusing or false \"not in the documents\" note passes, since every key fact is "
                  f"there.\n"]
    lines += [
             "Confusion (rows: person, columns: judge):\n",
             "| person \\ judge | " + " | ".join(LABELS) + " |", "|---|" + "---|" * len(LABELS)]
    for h in LABELS:
        lines.append(f"| {h} | " + " | ".join(str(res["confusion"][h][j]) for j in LABELS) + " |")
    lines += ["\n| id | person | judge (majority) | judge, every repeat | person's note | judge's reason |",
              "|---|---|---|---|---|---|"]
    for r in res["rows"]:
        mark = "" if r["agree"] else " ⚠️"
        lines.append(f"| {r['id']}{mark} | {r['human']} | {r['judge']} | {' / '.join(r['judge_runs'])} | "
                     f"{r['human_note']} | {r['judge_reason']} |")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- grading an evaluation run

def judge_run(tag: str = C.PROMPT_VERSION, prompt_version: str = C.JUDGE_PROMPT_VERSION, client=None) -> dict:
    """Grade every answer in evals/results/answers/<tag>/answers.jsonl; write judge_<version>.jsonl and .json."""
    from .answer_eval import load_testset
    folder = C.ANSWER_RESULTS / tag
    records = [json.loads(l) for l in (folder / "answers.jsonl").read_text(encoding="utf-8").splitlines()]
    expected = {q["id"]: q for q in load_testset()}
    client = client or make_client()
    prompt = load_prompt(prompt_version)
    with ThreadPoolExecutor(max_workers=C.EVAL_WORKERS) as pool:
        verdicts = list(pool.map(lambda r: judge_one(client, r["question"], expected[r["id"]]["expected_answer"],
                                                     r["text"], prompt), records))
    graded = [{"id": r["id"], "run": r["run"], "label": v["label"], "reason": v["reason"]} for r, v in zip(records, verdicts)]
    from .answer_eval import free_stem
    stem = free_stem(folder, f"judge_{prompt_version}", (".json", ".jsonl"))
    with open(stem.with_name(stem.name + ".jsonl"), "w", encoding="utf-8") as f:
        for g in graded:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")
    labels = Counter(g["label"] for g in graded)
    n = len(graded)
    summary = {"judge_prompt": prompt_version, "n": n, "labels": dict(labels),
               "correct": round(labels["correct"] / n, 3),
               "correct_or_partial": round((labels["correct"] + labels["partial"]) / n, 3),
               "score": round((labels["correct"] + 0.5 * labels["partial"]) / n, 3),
               "cost_usd": round(sum(v["cost_usd"] for v in verdicts), 5)}
    stem.with_name(stem.name + ".json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"judge on {tag}: {summary}")
    return summary
