"""Pipeline: run every ticket through every configuration, save the results and the metrics."""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import ValidationError

from .metrics import compute_metrics, format_tables
from .providers import NonRetryableError, make_provider
from .schema import TicketExtraction, json_schema

ROOT = Path(__file__).resolve().parent.parent


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_texts(path: Path) -> list[dict]:
    """Input texts: one `<id>.txt` file per ticket; the id is the file name."""
    return [{"id": p.stem, "text": p.read_text(encoding="utf-8").rstrip("\n")}
            for p in sorted(path.glob("*.txt"))]


def load_golden(path: Path) -> dict[str, dict]:
    """Golden set: one `<id>.json` file with the reference label per ticket."""
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(path.glob("*.json"))}


def build_user_message(text: str) -> str:
    return f'Ticket:\n"""\n{text}\n"""'


def call_model(provider, system: str, user: str, schema: dict, run: dict, req: dict) -> dict:
    """One ticket -> one result record.

    - network errors and timeouts: up to `max_retries` retries with backoff;
    - errors a retry cannot fix (NonRetryableError): failed immediately;
    - a response that fails schema validation: `max_repair_attempts` repair attempts, then status=failed.
    """
    t0 = time.perf_counter()
    in_tok = out_tok = attempts = repairs = net_failures = 0
    prompt, raw, error = user, None, None

    while True:
        attempts += 1
        try:
            res = provider.generate(system, prompt, schema, run.get("temperature"), run.get("top_p"),
                                    req["max_tokens"], req["timeout_s"])
        except NonRetryableError as e:
            error = f"{type(e).__name__}: {e}"
            break
        except Exception as e:  # timeout, network, 5xx
            error = f"{type(e).__name__}: {e}"
            net_failures += 1
            if net_failures > req["max_retries"]:
                break
            time.sleep(min(2 ** net_failures, 8))
            continue

        in_tok += res.input_tokens
        out_tok += res.output_tokens
        raw = res.text
        try:
            parsed = TicketExtraction.model_validate_json(raw)
            return _result(True, parsed.model_dump(mode="json"), raw, None, attempts, repairs, t0, in_tok, out_tok)
        except ValidationError as e:
            error = "invalid_schema: " + "; ".join(
                f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()[:3])
            if repairs >= req["max_repair_attempts"]:
                break
            repairs += 1
            prompt = (f"{user}\n\nYour previous answer was invalid ({error}).\n"
                      f"Previous answer: {raw}\nReturn a corrected object that matches the schema.")

    return _result(False, None, raw, error, attempts, repairs, t0, in_tok, out_tok)


def _result(valid, output, raw, error, attempts, repairs, t0, in_tok, out_tok) -> dict:
    return {
        "status": "ok" if valid else "failed", "valid": valid, "output": output, "raw": raw, "error": error,
        "attempts": attempts, "repairs": repairs, "latency_s": time.perf_counter() - t0,
        "input_tokens": in_tok, "output_tokens": out_tok,
    }


def run_config(run: dict, cfg: dict, tickets: list[dict], system: str, schema: dict,
               out_dir: Path, prompt_version: str) -> list[dict]:
    provider = make_provider(run["provider"], run["model"], run.get("options"))
    provider.check()
    out_path = out_dir / f"{run['name']}.jsonl"
    records = []
    with out_path.open("w", encoding="utf-8") as f:
        for i, t in enumerate(tickets, 1):
            r = call_model(provider, system, build_user_message(t["text"]), schema, run, cfg["request"])
            cost = (r["input_tokens"] * run.get("price_input_per_mtok", 0.0)
                    + r["output_tokens"] * run.get("price_output_per_mtok", 0.0)) / 1e6
            rec = {
                "id": t["id"], "run": run["name"], "provider": run["provider"], "model": run["model"],
                "prompt_version": prompt_version, "temperature": run.get("temperature"),
                "top_p": run.get("top_p"), "options": run.get("options"),
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                **r, "cost_usd": cost,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            records.append(rec)
            print(f"  [{run['name']}] {i}/{len(tickets)} {t['id']} {r['status']} {r['latency_s']:.2f}s", flush=True)
    return records


def latest_run_dir(root: Path) -> Path | None:
    dirs = sorted(p for p in root.glob("*") if p.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}_", p.name))
    return dirs[-1] if dirs else None


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles crash on non-ASCII output when redirected
    ap = argparse.ArgumentParser(description="Structured Extraction Service: compare models on ticket extraction")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--run", action="append", help="run only the configuration with this name (repeatable)")
    ap.add_argument("--limit", type=int, help="use only the first N tickets (quick check)")
    ap.add_argument("--prompt-version", help="override prompt_version from the config")
    ap.add_argument("--report-only", action="store_true",
                    help="do not call models, only recompute metrics from saved results")
    ap.add_argument("--results-dir", help="run folder for --report-only (default: the latest)")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    cfg = yaml.safe_load((ROOT / args.config).read_text(encoding="utf-8"))
    pv = args.prompt_version or cfg["prompt_version"]
    results_root = ROOT / cfg["data"]["results_dir"]
    results_root.mkdir(exist_ok=True)

    golden = load_golden(ROOT / cfg["data"]["golden"])
    runs = [r for r in cfg["runs"] if not args.run or r["name"] in args.run]
    all_records: dict[str, list[dict]] = {}
    skipped: list[str] = []

    if args.report_only:
        out_dir = Path(args.results_dir) if args.results_dir else latest_run_dir(results_root)
        if out_dir is None or not out_dir.exists():
            print("No saved runs in", results_root)
            return
        for p in sorted(out_dir.glob("*.jsonl")):
            if not args.run or p.stem in args.run:
                all_records[p.stem] = load_jsonl(p)
    else:
        tickets = load_texts(ROOT / cfg["data"]["texts"])
        if args.limit:
            tickets = tickets[: args.limit]
        system = (ROOT / "prompts" / f"{pv}.md").read_text(encoding="utf-8")
        schema = json_schema()
        out_dir = results_root / f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}__{pv}"
        out_dir.mkdir()
        print(f"Prompt {pv}, tickets: {len(tickets)}, configurations: {len(runs)}")
        for run in runs:
            print(f"\n== {run['name']} ({run['provider']}:{run['model']}, "
                  f"T={run.get('temperature')}, top_p={run.get('top_p')})")
            try:
                all_records[run["name"]] = run_config(run, cfg, tickets, system, schema, out_dir, pv)
            except Exception as e:  # e.g. no API key or Ollama is not running: skip, keep going
                print(f"  SKIPPED: {e}")
                skipped.append(f"{run['name']}: {e}")

    all_records = {name: recs for name, recs in all_records.items() if recs}
    if not all_records:
        print("\nNo results to compute metrics from.")
        return
    metrics = [compute_metrics(recs, golden) for recs in all_records.values()]
    (out_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    table = format_tables(metrics)
    (out_dir / "metrics.md").write_text(table + "\n", encoding="utf-8")
    print("\n" + table)
    if skipped:
        print("\nSkipped configurations:\n  " + "\n  ".join(skipped))
    print(f"\nResults: {out_dir}")
