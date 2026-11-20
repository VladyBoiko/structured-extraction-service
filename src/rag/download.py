"""Fetch the external public documents listed in the catalog (entries with a `url`).

Manufacturer manuals and legal texts are not committed: their owners publish them, we only link to them.
The catalog keeps the URL and the SHA-256 of the file we ingested; a different hash means the publisher
changed the document, which the manifest then shows as a new version.
"""

import hashlib
import time

import requests

from .catalog import load_catalog
from .config import RAW

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) rag-course-project/1.0"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download(force: bool = False) -> dict:
    catalog = load_catalog()
    summary = {"downloaded": 0, "present": 0, "failed": [], "changed": []}
    for path, entry in catalog.items():
        url = entry.get("url")
        if not url:
            continue
        target = RAW / path
        if target.exists() and not force:
            summary["present"] += 1
            continue
        try:
            resp = requests.get(url, headers=HEADERS, timeout=60)
            resp.raise_for_status()
        except requests.RequestException as e:
            summary["failed"].append(f"{path}: {e}")
            print(f"  FAILED {path}: {e}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(resp.content)
        digest = sha256(resp.content)
        expected = entry.get("sha256")
        if expected and expected != digest:
            summary["changed"].append(path)
            print(f"  CHANGED {path}: the publisher updated the file (sha256 {digest[:12]} != {expected[:12]})")
        summary["downloaded"] += 1
        print(f"  ok {path} ({len(resp.content) // 1024} KB)")
        time.sleep(0.5)  # be polite to public servers
    print(f"downloaded {summary['downloaded']}, already present {summary['present']}, "
          f"failed {len(summary['failed'])}")
    return summary
