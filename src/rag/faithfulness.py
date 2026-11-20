"""Faithfulness (step 4): is every claim of an answer supported by the sources it cites?

Two levels:
  1. deterministic, in answer.validate(): every quote is found word for word in the cited chunk; a claim without one
     verified quote is dropped before the customer sees it;
  2. here, an LLM reads each claim together with the full text of the chunks it cites and says whether the claim
     follows from them: a real quote can still back a claim that misstates it (another number, another product).

The checker is tested on control claims: real claims deliberately broken (a number changed, the claim of another
question put under these citations) that it has to reject.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor

import yaml

from . import config as C
from .answer import cost, make_client

SCHEMA = {
    "type": "object",
    "properties": {"claims": {"type": "array", "items": {
        "type": "object",
        "properties": {"index": {"type": "integer"}, "reason": {"type": "string"}, "supported": {"type": "boolean"}},
        "required": ["index", "reason", "supported"], "additionalProperties": False}}},
    "required": ["claims"],
    "additionalProperties": False,
}


def load_prompt(version: str = C.FAITHFULNESS_PROMPT_VERSION) -> str:
    return (C.FAITHFULNESS_PROMPTS_DIR / f"{version}.md").read_text(encoding="utf-8").strip()


def load_chunks() -> dict[str, dict]:
    return {r["chunk_id"]: r for r in map(json.loads, C.CHUNKS.read_text(encoding="utf-8").splitlines())}


def written_controls(chunks: dict[str, dict]) -> list[dict]:
    """evals/faithfulness_controls.yaml: claims that differ from their source in one detail (must be rejected) and
    correct restatements (must be accepted)."""
    items = yaml.safe_load(C.FAITHFULNESS_CONTROLS.read_text(encoding="utf-8"))["controls"]
    return [{"kind": c["kind"], "id": c["id"], "text": c["claim"], "expected": c["supported"],
             "citations": [{"chunk_id": cid, "title": chunks[cid]["title"]} for cid in c["citations"]]}
            for c in items]


def check(client, claims: list[dict], chunk_texts: dict[str, str], prompt: str) -> tuple[list[dict], float]:
    """claims: [{text, citations: [{chunk_id, title, section}]}] -> one verdict per claim, and the cost."""
    parts = []
    for k, claim in enumerate(claims):
        sources = []
        for chunk_id in dict.fromkeys(c["chunk_id"] for c in claim["citations"]):
            cit = next(c for c in claim["citations"] if c["chunk_id"] == chunk_id)
            sources.append(f"<source title=\"{cit['title']}\">\n{chunk_texts.get(chunk_id, '(not available)')}\n</source>")
        parts.append(f"<claim index=\"{k}\">\n<text>{claim['text']}</text>\n" + "\n".join(sources) + "\n</claim>")
    resp = client.messages.create(
        model=C.JUDGE_MODEL, max_tokens=8000,
        system=[{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": "\n\n".join(parts)}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}, "effort": C.JUDGE_EFFORT})
    u = resp.usage
    spent = cost(C.JUDGE_MODEL, u.input_tokens, u.output_tokens, getattr(u, "cache_creation_input_tokens", 0) or 0,
                 getattr(u, "cache_read_input_tokens", 0) or 0)
    if resp.stop_reason != "end_turn":
        return [{"supported": None, "reason": f"stop_reason={resp.stop_reason}"} for _ in claims], spent
    out = {c["index"]: c for c in json.loads(next(b.text for b in resp.content if b.type == "text"))["claims"]}
    return [out.get(k, {"supported": None, "reason": "no verdict"}) for k in range(len(claims))], spent


# ---------------------------------------------------------------- control claims

def change_number(text: str) -> str | None:
    """Replace the first number with another one (30 -> 60, 5,90 -> 8,90, 1 500 -> 3 000)."""
    m = re.search(r"\d+(?:[ ,.]\d+)*", text)
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(0))
    first = int(digits[0])
    new = str((first + 3) % 9 + 1) + digits[1:] if len(digits) > 1 else str(int(digits) * 2 + 1)
    fmt = new if m.group(0).isdigit() else re.sub(r"\d", lambda _, it=iter(new): next(it, ""), m.group(0))
    return text[:m.start()] + fmt + text[m.end():]


def controls(records: list[dict], n: int = 12) -> list[dict]:
    """Broken claims that must be rejected: half with a number changed, half with another question's claim under these
    citations. Deterministic: the first answer of each question, in test set order."""
    firsts = {}
    for r in records:
        if r["claims"] and r["id"] not in firsts:
            firsts[r["id"]] = r
    answers = list(firsts.values())
    out = []
    for r in answers:
        claim = next((c for c in r["claims"] if re.search(r"\d", c["text"])), None)
        changed = change_number(claim["text"]) if claim else None
        if changed and changed != claim["text"]:
            out.append({"kind": "number changed", "id": r["id"], "text": changed, "citations": claim["citations"]})
        if len([c for c in out if c["kind"] == "number changed"]) >= n // 2:
            break
    for a, b in zip(answers, answers[1:] + answers[:1]):
        out.append({"kind": "claim of another question", "id": a["id"], "text": b["claims"][0]["text"],
                    "citations": a["claims"][0]["citations"]})
        if len(out) >= n:
            break
    return out


# ---------------------------------------------------------------- an evaluation run

def run(tag: str = C.PROMPT_VERSION, prompt_version: str = C.FAITHFULNESS_PROMPT_VERSION, client=None) -> dict:
    folder = C.ANSWER_RESULTS / tag
    records = [json.loads(l) for l in (folder / "answers.jsonl").read_text(encoding="utf-8").splitlines()]
    answered = [r for r in records if r["claims"]]
    client = client or make_client()
    prompt = load_prompt(prompt_version)
    chunks = load_chunks()
    texts = {k: v["text"] for k, v in chunks.items()}
    ctrl = [{**c, "expected": False} for c in controls(answered)] + written_controls(chunks)
    jobs = [r["claims"] for r in answered] + [[c] for c in ctrl]
    with ThreadPoolExecutor(max_workers=C.EVAL_WORKERS) as pool:
        results = list(pool.map(lambda claims: check(client, claims, texts, prompt), jobs))
    spent = sum(c for _, c in results)

    rows = []
    for r, (verdicts, _) in zip(answered, results):
        for claim, v in zip(r["claims"], verdicts):
            rows.append({"id": r["id"], "run": r["run"], "claim": claim["text"], "supported": v.get("supported"),
                         "reason": v.get("reason", "")})
    ctrl_rows = [{**c, "supported": v[0].get("supported"), "reason": v[0].get("reason", "")}
                 for c, (v, _) in zip(ctrl, results[len(answered):])]
    by_answer = {}
    for row in rows:
        by_answer.setdefault((row["id"], row["run"]), []).append(row["supported"])
    dropped = sum(len(r["dropped"]) for r in records)
    shown = sum(len(r["claims"]) for r in records)
    summary = {
        "faithfulness_prompt": prompt_version, "answers": len(answered), "claims": len(rows),
        "quotes_verified": round(shown / (shown + dropped), 3) if shown + dropped else None,
        "claims_dropped_by_quote_check": dropped,
        "claims_supported": round(sum(r["supported"] is True for r in rows) / len(rows), 3) if rows else None,
        "answers_fully_supported": round(sum(all(v is True for v in vs) for vs in by_answer.values()) / len(by_answer), 3)
        if by_answer else None,
        "unsupported": [r for r in rows if r["supported"] is not True],
        **control_summary(ctrl_rows),
        "cost_usd": round(spent, 5),
    }
    from .answer_eval import free_stem
    stem = free_stem(folder, f"faithfulness_{prompt_version}", (".json", ".jsonl"))
    with open(stem.with_name(stem.name + ".jsonl"), "w", encoding="utf-8") as f:
        for row in rows + [{"control": True, **c} for c in ctrl_rows]:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    stem.with_name(stem.name + ".json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                                                                encoding="utf-8")
    print(f"faithfulness on {tag}: {summary['claims']} claims in {summary['answers']} answers; quotes verified "
          f"{summary['quotes_verified']}; supported {summary['claims_supported']}; answers fully supported "
          f"{summary['answers_fully_supported']}; ${summary['cost_usd']}")
    for kind, v in summary["control_groups"].items():
        print(f"  controls, {kind}: {v['right']}/{v['n']} judged as expected")
    for r in summary["unsupported"]:
        print(f"  unsupported {r['id']} run {r['run']}: {r['claim'][:100]} -- {r['reason']}")
    for c in summary["controls_wrong"]:
        print(f"  control wrong ({c['kind']}, expected {c['expected']}) {c['id']}: {c['text'][:90]} -- {c['reason']}")
    return summary


def control_summary(rows: list[dict]) -> dict:
    """Three groups: generated broken claims, written subtle errors (both must be rejected), correct restatements
    (must be accepted)."""
    def group(rs):
        return {"n": len(rs), "right": sum(r["supported"] is r["expected"] for r in rs)}
    generated = [r for r in rows if r["kind"] in ("number changed", "claim of another question")]
    written = [r for r in rows if r not in generated]
    groups = {"generated errors": group(generated),
              "subtle errors": group([r for r in written if r["expected"] is False]),
              "correct restatements": group([r for r in written if r["expected"] is True])}
    return {"control_groups": groups, "controls_wrong": [r for r in rows if r["supported"] is not r["expected"]]}
