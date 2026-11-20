"""Ingestion: raw files -> extracted text -> normalized -> deduplicated -> chunks with metadata + manifest.

Incremental: the extracted, normalized text of every file is cached by the file's SHA-256 and the
pipeline version. An unchanged file is not parsed again (the 180-page PDFs take seconds each); chunking
is cheap and always runs, so a change of chunking parameters applies to the whole corpus.
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from . import config as C
from .catalog import doc_id, load_catalog
from .chunking import Chunk, chunk_fixed, chunk_stats, chunk_structured, n_tokens, starts_clean
from .dedup import content_hash, near_duplicate_pairs
from .extract import extract
from .language import detect, foreign_share
from .normalize import normalize

# Documents the README compares chunking strategies on: one per format and size class.
COMPARISON_DOCS = ["returns_ua_2025", "delivery_dach", "payment_ua", "sony_wf1000xm5_help_guide_en",
                   "eu_directive_2011_83_consumer_rights_en", "jbl_tune_770nc_spec_en"]

META_FIELDS = ("doc_type", "topic", "language", "region", "version", "effective_date", "status",
               "superseded_by", "url")


@dataclass
class Doc:
    path: str                      # relative to data/rag/raw, posix
    entry: dict                    # catalog entry
    raw_hash: str = ""
    text: str = ""
    title: str = ""
    doc_hash: str = ""
    status: str = "ok"             # ok | exact_duplicate | near_duplicate | ocr_required | error | missing
    note: str = ""
    cached: bool = False
    language_detected: str | None = None
    foreign_share: float = 0.0
    chunks: list[Chunk] = field(default_factory=list)

    @property
    def id(self) -> str:
        return doc_id(self.path)

    @property
    def catalogued(self) -> bool:
        return "derive" not in self.entry


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------- extract (cached)

def load_text(doc: Doc, full: bool) -> None:
    cache = C.CACHE / f"{doc.raw_hash[:24]}-{C.PIPELINE_VERSION}.json"
    if cache.exists() and not full:
        data = json.loads(cache.read_text(encoding="utf-8"))
        doc.cached = True
    else:
        ex = extract(C.RAW / doc.path)
        data = {"text": "" if ex.needs_ocr else normalize(ex.text), "needs_ocr": ex.needs_ocr,
                "title_hint": ex.title_hint}
        C.CACHE.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    if data["needs_ocr"]:
        doc.status, doc.note = "ocr_required", "no text layer: send to OCR, not to the index"
        return
    doc.text = data["text"]
    doc.doc_hash = content_hash(doc.text)
    doc.title = doc.entry.get("title") or first_heading(doc.text) or data["title_hint"] or doc.id


def first_heading(text: str) -> str:
    for line in text.split("\n"):
        if line.startswith("# "):
            return line[2:].strip()[:150]
    return ""


# ---------------------------------------------------------------- dedup

def deduplicate(docs: list[Doc], report: dict) -> None:
    # Exact: same normalized content. Keep the catalogued document, drop the copy.
    by_hash: dict[str, Doc] = {}
    for doc in sorted((d for d in docs if d.status == "ok"), key=lambda d: not d.catalogued):
        keep = by_hash.setdefault(doc.doc_hash, doc)
        if keep is not doc:
            doc.status, doc.note = "exact_duplicate", f"same content as {keep.path}"
            report["exact_duplicates"].append({"dropped": doc.path, "kept": keep.path})

    # Near: shingle overlap. Two catalogued versions of one policy are kept on purpose (status metadata
    # tells retrieval which one is current); anything else keeps the catalogued / newer document.
    active = {d.path: d for d in docs if d.status == "ok"}
    for a, b, score in near_duplicate_pairs({p: d.text for p, d in active.items()}, C.NEAR_DUP_JACCARD):
        da, db = active[a], active[b]
        if da.status != "ok" or db.status != "ok":
            continue
        if da.catalogued and db.catalogued and da.entry["version"] != db.entry["version"]:
            report["near_duplicates"].append({"pair": [a, b], "jaccard": score, "action": "kept both: versions"})
            continue
        rank = lambda d: (d.catalogued, d.entry.get("effective_date", ""))
        older, newer = sorted([da, db], key=rank)
        older.status, older.note = "near_duplicate", f"near-duplicate of {newer.path} (jaccard {score})"
        report["near_duplicates"].append({"dropped": older.path, "kept": newer.path, "jaccard": score})


# ---------------------------------------------------------------- records

def chunk_record(doc: Doc, i: int, chunk: Chunk, prefix: str = "") -> dict:
    meta = {k: doc.entry.get(k) for k in META_FIELDS}
    return {
        "chunk_id": f"{prefix}{doc.id}#{i:03d}",
        "doc_id": doc.id,
        "source": doc.path,
        "title": doc.title,
        "section": chunk.section,
        "chunk_index": i,
        "format": Path(doc.path).suffix.lstrip("."),
        **meta,
        "doc_hash": doc.doc_hash,
        "n_tokens": chunk.tokens,
        "text": chunk.text,
        "pipeline_version": C.PIPELINE_VERSION,
    }


def write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def clean_starts(text: str, chunks: list[Chunk]) -> list[bool]:
    return [starts_clean(text, c.text) for c in chunks]



def prepare_docs(catalog: dict, on_disk: set[str], full: bool, report: dict) -> list["Doc"]:
    """Extract (or load from cache), deduplicate and language-check every catalogued file."""
    docs: list[Doc] = []
    for path, entry in catalog.items():
        doc = Doc(path, entry)
        docs.append(doc)
        if path not in on_disk:
            doc.status = "missing"
            doc.note = "run `python -m src.rag download`" if "url" in entry else "run `python -m src.rag build-store`"
            continue
        doc.raw_hash = sha256_file(C.RAW / path)
        try:
            load_text(doc, full)
        except Exception as e:   # one broken file must not stop the batch
            doc.status, doc.note = "error", f"{type(e).__name__}: {e}"
            report["errors"].append({"path": path, "error": doc.note})

    deduplicate(docs, report)

    for doc in docs:
        if doc.status != "ok":
            continue
        doc.language_detected = detect(doc.text)
        doc.foreign_share = foreign_share(doc.text, doc.entry["language"])
        if doc.language_detected != doc.entry["language"] or doc.foreign_share > C.LANG_MIXED_WARN:
            report["language"].append({"path": doc.path, "declared": doc.entry["language"],
                                       "detected": doc.language_detected, "foreign_share": doc.foreign_share})
    return docs


def structured_variant(max_tokens: int, min_tokens: int) -> list[dict]:
    """Chunk records with other structure-aware parameters, from the cached texts: for the size sweep."""
    catalog = load_catalog()
    on_disk = {p.relative_to(C.RAW).as_posix() for p in C.RAW.rglob("*") if p.is_file()}
    report = {"exact_duplicates": [], "near_duplicates": [], "language": [], "errors": []}
    docs = [d for d in prepare_docs(catalog, on_disk, False, report) if d.status == "ok"]
    return [chunk_record(d, i, c) for d in docs
            for i, c in enumerate(chunk_structured(d.text, max_tokens, min_tokens))]

# ---------------------------------------------------------------- run

def run(full: bool = False) -> dict:
    catalog = load_catalog()
    report = {"exact_duplicates": [], "near_duplicates": [], "language": [], "errors": [], "uncatalogued": []}

    on_disk = {p.relative_to(C.RAW).as_posix() for p in C.RAW.rglob("*") if p.is_file() and not p.name.startswith(".")}
    report["uncatalogued"] = sorted(on_disk - set(catalog))

    docs = prepare_docs(catalog, on_disk, full, report)

    # Chunk both ways: structure-aware is indexed, fixed-size is the baseline for the comparison.
    records, fixed_records = [], []
    totals = {"structured": ([], []), "fixed": ([], [])}
    per_doc = {}
    for doc in docs:
        if doc.status != "ok":
            continue
        # FAQ_CHUNKS = per_question: an FAQ is a list of unrelated questions, merged they score low (step 4)
        per_question = C.FAQ_CHUNKS == "per_question" and doc.entry.get("doc_type") == "faq"
        doc.chunks = chunk_structured(doc.text, merge_siblings=not per_question)
        fixed = chunk_fixed(doc.text)
        records += [chunk_record(doc, i, c) for i, c in enumerate(doc.chunks)]
        fixed_records += [chunk_record(doc, i, c, prefix="fixed:") for i, (c, _) in enumerate(fixed)]
        s_clean = clean_starts(doc.text, doc.chunks)
        f_clean = clean_starts(doc.text, [c for c, _ in fixed])
        totals["structured"][0].extend(doc.chunks)
        totals["structured"][1].extend(s_clean)
        totals["fixed"][0].extend(c for c, _ in fixed)
        totals["fixed"][1].extend(f_clean)
        if doc.id in COMPARISON_DOCS:
            per_doc[doc.id] = {"tokens": n_tokens(doc.text),
                               "structured": chunk_stats(doc.chunks, s_clean),
                               "fixed": chunk_stats([c for c, _ in fixed], f_clean)}
    report["chunking"] = {
        "params": {"chunker": C.CHUNKER_VERSION,
                   "structured": {"max_tokens": C.CHUNK_MAX_TOKENS, "min_tokens": C.CHUNK_MIN_TOKENS,
                                  "faq": C.FAQ_CHUNKS},
                   "fixed": {"tokens": C.FIXED_TOKENS, "overlap": C.FIXED_OVERLAP}, "tokenizer": C.TOKENIZER},
        "corpus": {name: chunk_stats(*v) for name, v in totals.items()},
        "documents": per_doc,
    }

    write_jsonl(C.CHUNKS, records)
    write_jsonl(C.CHUNKS_FIXED, fixed_records)

    files = {}
    for d in docs:
        files[d.path] = {
            "doc_id": d.id, "ingest_status": d.status, "note": d.note, "title": d.title,
            "format": Path(d.path).suffix.lstrip("."),
            "raw_hash": d.raw_hash, "doc_hash": d.doc_hash,
            **({k: d.entry.get(k) for k in META_FIELDS} if d.catalogued else {"derived_from": d.entry["derive"]["from"]}),
            "language_detected": d.language_detected, "foreign_share": d.foreign_share,
            "tokens": n_tokens(d.text) if d.text else 0, "chunks": len(d.chunks),
        }
    version = hashlib.sha256(json.dumps({"pipeline": C.PIPELINE_VERSION, "chunking": report["chunking"]["params"],
                                         "files": {p: f["raw_hash"] for p, f in files.items()}},
                                        sort_keys=True).encode()).hexdigest()[:12]
    counts: dict[str, int] = {}
    for f in files.values():
        counts[f["ingest_status"]] = counts.get(f["ingest_status"], 0) + 1
    manifest = {"dataset_version": f"ds-{version}", "pipeline_version": C.PIPELINE_VERSION,
                "chunking": report["chunking"]["params"], "counts": counts,
                "chunks": len(records), "files": files}
    C.MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["dataset_version"] = manifest["dataset_version"]
    report["counts"] = counts
    report["cached"] = sum(d.cached for d in docs)
    C.INGEST_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"report": report, "manifest": manifest, "docs": docs}


def print_summary(result: dict) -> None:
    report, manifest, docs = result["report"], result["manifest"], result["docs"]
    print(f"{'document':<46} {'fmt':<5} {'lang':<5} {'status':<16} {'tokens':>7} {'chunks':>6}  note")
    for d in docs:
        f = manifest["files"][d.path]
        print(f"{d.id[:46]:<46} {f['format']:<5} {(d.entry.get('language') or '-'):<5} {d.status:<16} "
              f"{f['tokens']:>7} {f['chunks']:>6}  {d.note}")
    for w in report["language"]:
        print(f"LANGUAGE WARNING {w['path']}: declared {w['declared']}, detected {w['detected']}, "
              f"foreign paragraphs {w['foreign_share']:.0%}")
    for e in report["errors"]:
        print(f"ERROR {e['path']}: {e['error']}")
    for p in report["uncatalogued"]:
        print(f"NOT IN CATALOG (skipped): {p}")
    print("\nchunking (whole corpus)  chunks  avg tok  max tok  <40 tok  mid-sentence start  cut tables  mixes sections")
    for name, s in report["chunking"]["corpus"].items():
        print(f"{name:<24} {s['chunks']:>6} {s['avg_tokens']:>8} {s['max_tokens']:>8} {s['under_40_tokens']:>8}"
              f" {s['starts_mid_sentence']:>19} {s['cut_tables']:>11} {s['mixes_sections']:>15}")
    print(f"\ndataset {manifest['dataset_version']} | files {len(docs)} | {manifest['counts']} | "
          f"chunks {manifest['chunks']} | parsed {len(docs) - report['cached']}, from cache {report['cached']}")
