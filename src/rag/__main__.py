"""RAG pipeline commands. Block 1 (main.py) is not touched by any of them.

    python -m src.rag build-store      render the store documents (data/rag/authoring -> data/rag/raw/store)
    python -m src.rag download         fetch the external public documents (data/rag/raw/external)
    python -m src.rag ingest [--full]  extract, clean, deduplicate, chunk -> data/rag/chunks.jsonl + manifest.json
    python -m src.rag data             build-store + download + ingest
    python -m src.rag index            embed the chunks and (re)build the Qdrant collections
    python -m src.rag search "query" [--mode rerank] [--region UA INTL] [--all-versions]
    python -m src.rag eval-retrieval [--models minilm mpnet e5-large]
"""

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")   # Ukrainian and German text on a Windows console
    ap = argparse.ArgumentParser(prog="python -m src.rag", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build-store", help="render store documents to md/docx/html")
    d = sub.add_parser("download", help="fetch external documents")
    d.add_argument("--force", action="store_true", help="download again even if the file exists")
    i = sub.add_parser("ingest", help="extract, clean, deduplicate and chunk the corpus")
    i.add_argument("--full", action="store_true", help="ignore the extraction cache")
    sub.add_parser("data", help="build-store + download + ingest")
    sub.add_parser("index", help="embed chunks and build the Qdrant collections")
    s = sub.add_parser("search", help="search the index")
    s.add_argument("query")
    s.add_argument("--mode", choices=["vector", "bm25", "hybrid", "rerank"], default="rerank")
    s.add_argument("-k", type=int, default=5)
    s.add_argument("--region", nargs="+", help="UA DACH INTL EU DE GLOBAL")
    s.add_argument("--language", nargs="+", help="uk en de")
    s.add_argument("--doc-type", nargs="+", help="policy faq product_page service spec_sheet manual law")
    s.add_argument("--as-of", help="only documents in force on this date, YYYY-MM-DD")
    s.add_argument("--all-versions", action="store_true", help="include superseded documents")
    s.add_argument("--fixed", action="store_true", help="search the fixed-size chunks instead")
    e = sub.add_parser("eval-retrieval", help="recall@k / MRR of all configurations")
    e.add_argument("--models", nargs="+", help="embedding models to compare (vector search)")
    e.add_argument("--sweep", action="store_true", help="also compare structure-aware chunk sizes (slow: re-embeds)")
    args = ap.parse_args(argv)

    if args.cmd in ("build-store", "data"):
        from .build_store import build_store
        build_store()
    if args.cmd in ("download", "data"):
        from .download import download
        summary = download(force=getattr(args, "force", False))
        if summary["failed"]:
            print("some downloads failed; ingestion marks those documents as missing")
    if args.cmd in ("ingest", "data"):
        from .ingest import print_summary, run
        print_summary(run(full=getattr(args, "full", False)))
    if args.cmd == "index":
        from . import config as C
        from .retrieve import Retriever
        for name, path in (("structured", C.CHUNKS), ("fixed", C.CHUNKS_FIXED)):
            r = Retriever.build(path, name)
            print(f"{r.collection}: {len(r.chunks)} chunks, {'built' if r.built_now else 'up to date'}, "
                  f"embedded now {r.embedder.last_computed}")
    if args.cmd == "search":
        from . import config as C
        from .retrieve import Filters, Retriever
        r = Retriever.build(C.CHUNKS_FIXED if args.fixed else C.CHUNKS, "fixed" if args.fixed else "structured")
        flt = Filters(status=None if args.all_versions else "current", regions=args.region,
                      languages=args.language, doc_types=args.doc_type, as_of=args.as_of)
        for h in r.search(args.query, mode=args.mode, filters=flt, k=args.k):
            print(f"{h['rank']:>2}. {h['score']:8.3f}  {h['chunk_id']:<44} [{h['status']}, {h['region']}, {h['language']}]")
            print(f"    {h['section'][:110]}")
            print(f"    {' '.join(h['text'].split())[:200]}")
    if args.cmd == "eval-retrieval":
        from .retrieval_eval import run as eval_run
        eval_run(models=args.models, sweep=args.sweep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
