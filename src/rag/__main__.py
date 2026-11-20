"""RAG pipeline commands. Block 1 (main.py) is not touched by any of them.

    python -m src.rag build-store      render the store documents (data/rag/authoring -> data/rag/raw/store)
    python -m src.rag download         fetch the external public documents (data/rag/raw/external)
    python -m src.rag ingest [--full]  extract, clean, deduplicate, chunk -> data/rag/chunks.jsonl + manifest.json
    python -m src.rag data             build-store + download + ingest
    python -m src.rag index            embed the chunks and (re)build the Qdrant collections
    python -m src.rag search "query" [--mode rerank] [--region UA INTL] [--all-versions]
    python -m src.rag eval-retrieval [--models minilm mpnet e5-large]
    python -m src.rag ask "question" [--region UA] [--prompt v1] [--json]
    python -m src.rag eval [--runs 3] [--prompt v1] [--ids t01 t02] [--tag name]
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
    e.add_argument("--tag", help="results folder under evals/results/retrieval/ (earlier runs are never overwritten)")
    a = sub.add_parser("ask", help="answer a question with sources (calls Claude; needs ANTHROPIC_API_KEY in .env)")
    a.add_argument("question")
    a.add_argument("--region", nargs="+", help="UA DACH INTL EU DE GLOBAL")
    a.add_argument("--language", nargs="+", help="only documents in these languages: uk en de")
    a.add_argument("--doc-type", nargs="+", help="policy faq product_page service spec_sheet manual law")
    a.add_argument("--as-of", help="only documents in force on this date, YYYY-MM-DD")
    a.add_argument("--all-versions", action="store_true", help="include superseded documents")
    a.add_argument("--prompt", help="prompt version in prompts/rag/ (default: PROMPT_VERSION in config)")
    a.add_argument("--json", action="store_true", help="print the full record: context, claims, rejected quotes, usage")
    v = sub.add_parser("eval", help="answer the test set and score the answers (calls Claude)")
    v.add_argument("--runs", type=int, help="answers per question (default: EVAL_RUNS in config)")
    v.add_argument("--prompt", help="prompt version in prompts/rag/")
    v.add_argument("--ids", nargs="+", help="only these questions, e.g. t01 t12")
    v.add_argument("--tag", help="results folder name under evals/results/answers/ (default: the prompt version)")
    v.add_argument("--rescore", action="store_true", help="score the saved answers again, without calling the model")
    jc = sub.add_parser("judge-calibrate", help="agreement of the LLM judge with the human labels")
    jc.add_argument("--judge-prompt", help="judge prompt version in prompts/judge/")
    jc.add_argument("--holdout", action="store_true", help="use the fresh answers (evals/judge_holdout.yaml)")
    j = sub.add_parser("judge", help="grade every answer of an evaluation run with the LLM judge")
    j.add_argument("--tag", help="evaluation run under evals/results/answers/ (default: the answer prompt version)")
    j.add_argument("--judge-prompt", help="judge prompt version in prompts/judge/")
    j.add_argument("--latest", action="store_true", help="the newest of tag, tag_2 ... (the run eval just wrote)")
    ci =sub.add_parser("ci-check", help="compare an evaluation run with the CI gates (exit 1 on failure)")
    ci.add_argument("--answers", default="ci", help="answer run under evals/results/answers/ (newest of name, name_2 ...); 'none' to skip")
    ci.add_argument("--retrieval", default="ci", help="retrieval run under evals/results/retrieval/; 'none' to skip")
    bl = sub.add_parser("baseline", help="accept an answer run as evals/baseline.json for the regression gates")
    bl.add_argument("tag")
    rq = sub.add_parser("eval-retrieval-quick", help="retrieval evaluation of the configuration in use only (CI)")
    rq.add_argument("--tag", default="ci")
    fa = sub.add_parser("faithfulness", help="check that every claim follows from the sources it cites")
    fa.add_argument("--tag", help="evaluation run under evals/results/answers/ (default: the answer prompt version)")
    fa.add_argument("--latest", action="store_true", help="the newest of tag, tag_2 ... (the run eval just wrote)")
    args = ap.parse_args(argv)

    def answers_tag(tag: str) -> str:
        """With --latest: eval never overwrites, so a repeated run lands in tag_2, tag_3 ...; take the newest."""
        if not getattr(args, "latest", False):
            return tag
        from . import config as C
        from .ci import latest
        return latest(C.ANSWER_RESULTS, tag).name

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
        eval_run(models=args.models, sweep=args.sweep, tag=args.tag)
    if args.cmd == "ask":
        import json
        from . import config as C
        from .answer import answer
        from .retrieve import Filters, Retriever
        r = Retriever.build(C.CHUNKS, "structured")
        flt = Filters(status=None if args.all_versions else "current", regions=args.region,
                      languages=args.language, doc_types=args.doc_type, as_of=args.as_of)
        res = answer(args.question, r, filters=flt, prompt_version=args.prompt or C.PROMPT_VERSION)
        if args.json:
            print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(res.text)
            print(f"\n[{res.status} | prompt {res.prompt_version} | {res.model} | context {len(res.context)} chunks, "
                  f"{res.context_tokens} tokens | top score {res.top_score if res.top_score is None else round(res.top_score, 2)} | "
                  f"tokens in/out {res.input_tokens}/{res.output_tokens} | ${res.cost_usd:.5f} | {res.latency_ms} ms]")
            for claim in res.dropped:
                print(f"[dropped, no verified source: {claim.text}]")
            if res.error:
                print(f"[error: {res.error}]")
    if args.cmd == "eval":
        from . import config as C
        from .answer_eval import rescore, run as eval_answers
        if args.rescore:
            rescore(tag=args.tag or args.prompt or C.PROMPT_VERSION)
            return 0
        eval_answers(runs=args.runs or C.EVAL_RUNS, prompt_version=args.prompt or C.PROMPT_VERSION,
                     ids=args.ids, tag=args.tag)
    if args.cmd == "judge-calibrate":
        from . import config as C
        from .judge import calibrate
        if args.holdout:
            calibrate(prompt_version=args.judge_prompt or C.JUDGE_PROMPT_VERSION, labels_file=C.JUDGE_HOLDOUT,
                      name="holdout", answers_tag="v2-threshold")
        else:
            calibrate(prompt_version=args.judge_prompt or C.JUDGE_PROMPT_VERSION)
    if args.cmd == "judge":
        from . import config as C
        from .judge import judge_run
        judge_run(tag=answers_tag(args.tag or C.PROMPT_VERSION),prompt_version=args.judge_prompt or C.JUDGE_PROMPT_VERSION)
    if args.cmd == "ci-check":
        from .ci import check
        return 0 if check(None if args.answers == "none" else args.answers,
                          None if args.retrieval == "none" else args.retrieval) else 1
    if args.cmd == "baseline":
        from .ci import write_baseline
        write_baseline(args.tag)
    if args.cmd == "eval-retrieval-quick":
        from .retrieval_eval import run_quick
        run_quick(args.tag)
    if args.cmd == "faithfulness":
        from . import config as C
        from .faithfulness import run as faithfulness_run
        faithfulness_run(tag=answers_tag(args.tag or C.PROMPT_VERSION))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
