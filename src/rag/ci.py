"""CI quality gates: compare an evaluation run with evals/ci_thresholds.yaml and evals/baseline.json.

    python -m src.rag ci-check --answers ci --retrieval ci

Prints a table, appends it to the GitHub job summary when running in Actions, and exits with 1 when a gate fails.
"""

import json
import os
from pathlib import Path

import yaml

from . import config as C

THRESHOLDS = C.EVALS / "ci_thresholds.yaml"
BASELINE = C.EVALS / "baseline.json"


def latest(folder: Path, name: str) -> Path:
    """name, or the newest of name_2, name_3 ... (a run never overwrites an earlier one)."""
    candidates = [p for p in folder.glob(f"{name}*") if p.is_dir() and (p.name == name or p.name.startswith(name + "_"))]
    if not candidates:
        raise SystemExit(f"no results for {name} in {folder}")
    return max(candidates, key=lambda p: (p / "results.json").stat().st_mtime)


def check(answers_tag: str | None = "ci", retrieval_tag: str | None = "ci") -> bool:
    """answers_tag / retrieval_tag None: skip that group (no API key: only retrieval is evaluated)."""
    gates = yaml.safe_load(THRESHOLDS.read_text(encoding="utf-8"))
    answers_dir = latest(C.ANSWER_RESULTS, answers_tag) if answers_tag else None
    answers = json.loads((answers_dir / "results.json").read_text(encoding="utf-8")) if answers_dir else {}
    rows = []

    def gate(group: str, metric: str, value, rule: dict):
        if value is None:
            rows.append((group, metric, "-", rule, False))
            return
        ok = True
        if "min" in rule:
            ok &= value >= rule["min"]
        if "max" in rule:
            ok &= value <= rule["max"]
        rows.append((group, metric, value, rule, ok))

    if retrieval_tag:
        retrieval_dir = latest(C.RETRIEVAL_RESULTS, retrieval_tag)
        retrieval = json.loads((retrieval_dir / "results.json").read_text(encoding="utf-8"))
        modes = retrieval["modes"]   # the configuration in use: with translation when it was measured
        mode = modes.get("structured/rerank+translation") or modes.get("structured/rerank") or next(iter(modes.values()))
        for metric, rule in gates["retrieval"].items():
            gate("retrieval", metric, mode.get(metric), rule)
    for metric, rule in (gates["answers"].items() if answers else []):
        gate("answers", metric, answers.get(metric), rule)
    if answers and BASELINE.exists():
        base = json.loads(BASELINE.read_text(encoding="utf-8"))
        for metric, rule in gates["regression"].items():
            floor = round(base[metric] - rule["max_drop"], 3)
            gate("regression", metric, answers.get(metric), {"min": floor, "baseline": base[metric]})

    title = (f"{answers_dir.name}, {answers.get('questions')} questions x {answers.get('runs')} run" if answers
             else "retrieval only: no API key, answers not evaluated")
    lines = [f"### RAG quality gates ({title})",
             "", "| | metric | value | gate | |", "|---|---|---|---|---|"]
    for group, metric, value, rule, ok in rows:
        shown = f"{value:.3f}" if isinstance(value, float) else str(value)
        rule_text = ", ".join(f"{k} {v}" for k, v in rule.items())
        lines.append(f"| {group} | {metric} | {shown} | {rule_text} | {'✅' if ok else '❌'} |")
    failed = [r for r in rows if not r[4]]
    lines += ["", f"**{'All gates passed' if not failed else f'{len(failed)} gate(s) failed'}**"
                  + (f"; cost of this evaluation ${answers.get('total_cost_usd')}, "
                     f"${answers.get('cost_per_1000')} per 1,000 questions." if answers else ".")]
    if answers.get("always_fail"):
        lines.append(f"Questions failed: {', '.join(answers['always_fail'])}.")
    text = "\n".join(lines) + "\n"
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text)
    return not failed


def write_baseline(tag: str) -> dict:
    """Accept a run as the baseline the regression gates compare with."""
    res = json.loads((C.ANSWER_RESULTS / tag / "results.json").read_text(encoding="utf-8"))
    base = {k: res[k] for k in ("pass", "decision", "false_not_found", "answered_unanswerable", "language")}
    base.update({"from": tag, "prompt_version": res.get("prompt_version"), "pipeline": res.get("pipeline"),
                 "runs": res.get("runs"), "questions": res.get("questions")})
    BASELINE.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"baseline from {tag}: {base}")
    return base
