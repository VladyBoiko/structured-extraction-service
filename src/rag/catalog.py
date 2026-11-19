"""The corpus catalog (data/rag/catalog.yaml): which files exist and what we know about them."""

from pathlib import PurePosixPath

import yaml

from .config import CATALOG

DOC_TYPES = {"policy", "faq", "product_page", "service", "spec_sheet", "manual", "law"}
REGIONS = {"UA", "DACH", "INTL", "EU", "DE", "GLOBAL"}
LANGUAGES = {"uk", "en", "de"}
STATUSES = {"current", "superseded"}
REQUIRED = ("doc_type", "topic", "language", "region", "version", "effective_date", "status")


def doc_id(path: str) -> str:
    """Short stable id used in chunk ids and citations: the file name without the extension."""
    return PurePosixPath(path).stem


def load_catalog(path=CATALOG) -> dict[str, dict]:
    """Catalog entries by path. Raises ValueError with every problem found, not just the first."""
    entries = yaml.safe_load(path.read_text(encoding="utf-8"))["documents"]
    by_path: dict[str, dict] = {}
    errors: list[str] = []
    ids: dict[str, str] = {}
    for e in entries:
        p = e["path"]
        if p in by_path:
            errors.append(f"{p}: listed twice")
        by_path[p] = e
        did = doc_id(p)
        if did in ids:
            errors.append(f"{p}: doc id '{did}' clashes with {ids[did]}")
        ids[did] = p
        if "derive" in e:
            continue  # duplicates made on purpose carry no metadata of their own
        missing = [k for k in REQUIRED if k not in e]
        if missing:
            errors.append(f"{p}: missing {', '.join(missing)}")
            continue
        for key, allowed in (("doc_type", DOC_TYPES), ("region", REGIONS), ("language", LANGUAGES),
                             ("status", STATUSES)):
            if e[key] not in allowed:
                errors.append(f"{p}: {key}={e[key]!r} not in {sorted(allowed)}")
        if e["status"] == "superseded" and "superseded_by" not in e:
            errors.append(f"{p}: superseded but no superseded_by")
        if "authoring" not in e and "url" not in e:
            errors.append(f"{p}: neither authoring nor url")
    for e in entries:
        target = e.get("superseded_by")
        if target and target not in by_path:
            errors.append(f"{e['path']}: superseded_by {target} is not in the catalog")
    if errors:
        raise ValueError("catalog errors:\n  " + "\n  ".join(errors))
    return by_path
