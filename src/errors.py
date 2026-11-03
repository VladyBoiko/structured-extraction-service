"""Error analysis: where model answers differ from the golden set. Reads results/ only, calls no models.

Examples:
    python -m src.errors                            # latest run, all configurations
    python -m src.errors --run local_t0             # a single configuration
    python -m src.errors results/<run-folder>       # a specific run
    python -m src.errors --out results/errors.txt   # write to a UTF-8 file (PowerShell `>` breaks the encoding)
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.metrics import FIELDS, _get, _norm  # noqa: E402
from src.pipeline import latest_run_dir, load_golden, load_jsonl, load_texts  # noqa: E402


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # keep non-ASCII ticket text from crashing the Windows console
    ap = argparse.ArgumentParser(description="Error analysis of model answers against the golden set")
    ap.add_argument("run_dir", nargs="?", help="run folder (default: the latest)")
    ap.add_argument("--root", default="results", help="where to look for runs")
    ap.add_argument("--run", action="append", help="only this configuration (repeatable)")
    ap.add_argument("--out", help="write the report to a UTF-8 file (safer than `>` in PowerShell)")
    args = ap.parse_args()
    if args.out:
        sys.stdout = open(args.out, "w", encoding="utf-8")

    run_dir = Path(args.run_dir) if args.run_dir else latest_run_dir(ROOT / args.root)
    if run_dir is None or not run_dir.exists():
        sys.exit("No saved runs")

    texts = {t["id"]: t["text"] for t in load_texts(ROOT / "data" / "texts")}
    golden = load_golden(ROOT / "data" / "golden")
    print(f"Run: {run_dir.name}, golden set: {len(golden)} tickets")

    for path in sorted(run_dir.glob("*.jsonl")):
        if args.run and path.stem not in args.run:
            continue
        recs = load_jsonl(path)
        print(f"\n{'=' * 72}\n{path.stem}  ({recs[0]['model']}, prompt {recs[0]['prompt_version']})")

        print("\nValue distribution over all tickets (one value almost everywhere means the field collapsed):")
        for f in FIELDS:
            counts = Counter(str(_get(r["output"], f)) for r in recs if r["valid"])
            print(f"  {f}: " + ", ".join(f"{k}={v}" for k, v in counts.most_common()))

        for r in recs:
            if not r["valid"]:
                print(f"  FAILED {r['id']}: {r['error']}")

        print("\nDifferences from golden:")
        shown = 0
        for r in recs:
            gold = golden.get(r["id"])
            if gold is None:
                continue
            diffs = []
            for f in FIELDS:
                expected = _get(gold, f)
                got = _get(r["output"], f) if r["valid"] else "<failed>"
                if _norm(f, expected) != _norm(f, got):
                    diffs.append((f, expected, got))
            if diffs:
                shown += 1
                print(f"\n{r['id']}: {texts[r['id']][:100]}")
                for f, expected, got in diffs:
                    print(f"    {f}: expected {expected!r}, got {got!r}")
        if not shown:
            print("  none")


if __name__ == "__main__":
    main()
