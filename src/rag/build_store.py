"""Render the synthetic store documents into the formats the store publishes them in.

The store texts are written once as markdown in data/rag/authoring/. The catalog decides the published
format: .md is copied, .docx is generated with real Word styles (Title, Heading, List, Table), .html is a
full web page with navigation, a cookie banner, breadcrumbs and a footer around the article. The ingestion
pipeline then has to undo all of that, exactly as it would for documents exported from a real CMS.

Deliberate duplicates (catalog entries with `derive`) are made here too, for the deduplication check.
"""

import datetime as dt
import html
import io
import re
import zipfile
from pathlib import Path

from docx import Document
from docx.shared import Pt

from .catalog import load_catalog
from .config import AUTHORING, RAW

# ---------------------------------------------------------------- tiny markdown reader
# The authoring files use a small, regular subset of markdown: #-headings, paragraphs,
# "- " and "1. " lists and pipe tables. That is all the renderers need.


def parse_markdown(text: str) -> list[tuple]:
    """Blocks in order: ("h", level, text) | ("p", text) | ("ul", [items]) | ("ol", [items]) | ("table", rows)."""
    blocks: list[tuple] = []
    for raw in re.split(r"\n\s*\n", text.strip()):
        lines = [l.rstrip() for l in raw.strip().split("\n")]
        first = lines[0]
        if first.startswith("#"):
            level = len(first) - len(first.lstrip("#"))
            blocks.append(("h", level, first.lstrip("#").strip()))
            if len(lines) > 1:
                blocks.extend(parse_markdown("\n".join(lines[1:])))
        elif first.startswith("|"):
            rows = [[c.strip() for c in l.strip().strip("|").split("|")] for l in lines
                    if not re.fullmatch(r"\|?[\s:|-]+\|?", l)]
            blocks.append(("table", rows))
        elif first.startswith("- "):
            blocks.append(("ul", [l[2:].strip() for l in lines]))
        elif re.match(r"\d+\.\s", first):
            blocks.append(("ol", [re.sub(r"^\d+\.\s+", "", l) for l in lines]))
        else:
            blocks.append(("p", " ".join(lines)))
    return blocks


def title_of(blocks: list[tuple]) -> str:
    return next((b[2] for b in blocks if b[0] == "h" and b[1] == 1), "ElectroStore")


# ---------------------------------------------------------------- DOCX

FIXED_TIME = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)  # stable document properties


def render_docx(blocks: list[tuple], path: Path) -> None:
    doc = Document()
    doc.core_properties.title = title_of(blocks)
    doc.core_properties.author = "ElectroStore Customer Care"
    doc.core_properties.created = doc.core_properties.modified = FIXED_TIME
    # Page header and footer live outside the document body: a text extractor that walks the body
    # must not pick them up, and ours does not.
    section = doc.sections[0]
    section.header.paragraphs[0].text = "ElectroStore - Customer policies - internal copy"
    section.footer.paragraphs[0].text = "ElectroStore - confidential until published"

    for block in blocks:
        kind = block[0]
        if kind == "h":
            _, level, text = block
            doc.add_paragraph(text, style="Title" if level == 1 else f"Heading {level - 1}")
        elif kind == "p":
            doc.add_paragraph(block[1])
        elif kind in ("ul", "ol"):
            style = "List Bullet" if kind == "ul" else "List Number"
            for item in block[1]:
                doc.add_paragraph(item, style=style)
        elif kind == "table":
            rows = block[1]
            table = doc.add_table(rows=len(rows), cols=len(rows[0]))
            table.style = "Table Grid"
            for r, row in enumerate(rows):
                for c, value in enumerate(row):
                    cell = table.cell(r, c)
                    cell.text = value
                    if r == 0:
                        for run in cell.paragraphs[0].runs:
                            run.bold = True
                            run.font.size = Pt(10)
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    doc.save(buf)
    path.write_bytes(deterministic_zip(buf.getvalue()))


def deterministic_zip(data: bytes) -> bytes:
    """A .docx is a zip whose entries carry the current time: the same text would get a new file hash
    on every build. Rewrite the entries with a fixed timestamp so unchanged documents stay byte-identical."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            fixed = zipfile.ZipInfo(info.filename, date_time=(2025, 1, 1, 0, 0, 0))
            fixed.compress_type = zipfile.ZIP_DEFLATED
            dst.writestr(fixed, src.read(info.filename))
    return out.getvalue()


# ---------------------------------------------------------------- HTML

def _inline(text: str) -> str:
    return html.escape(text, quote=False)


def article_html(blocks: list[tuple]) -> str:
    out: list[str] = []
    for block in blocks:
        kind = block[0]
        if kind == "h":
            out.append(f"<h{block[1]}>{_inline(block[2])}</h{block[1]}>")
        elif kind == "p":
            out.append(f"<p>{_inline(block[1])}</p>")
        elif kind in ("ul", "ol"):
            items = "".join(f"<li>{_inline(i)}</li>" for i in block[1])
            out.append(f"<{kind}>{items}</{kind}>")
        elif kind == "table":
            head, *body = block[1]
            th = "".join(f"<th>{_inline(c)}</th>" for c in head)
            trs = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>" for row in body)
            out.append(f"<table class=\"policy-table\"><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>")
    return "\n".join(out)


SITE_TEMPLATE = """<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<title>{title} | ElectroStore</title>
<link rel="stylesheet" href="/static/site.css">
<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}gtag('js',new Date());</script>
</head>
<body>
<header class="site-header">
  <a class="logo" href="/">ElectroStore</a>
  <nav class="main-nav"><a href="/smartphones">Smartphones</a> <a href="/laptops">Laptops</a> <a href="/audio">Audio</a>
  <a href="/tv">TV</a> <a href="/appliances">Appliances</a> <a href="/sale">Sale %</a></nav>
  <form class="search" action="/search"><input name="q" placeholder="Search"><button>Search</button></form>
</header>
<div id="cookie-banner" class="cookie-consent">We use cookies to improve your experience.
  <button>Accept all</button> <button>Settings</button></div>
<nav class="breadcrumbs"><a href="/">Home</a> &rsaquo; <a href="/help">Help</a> &rsaquo; {title}</nav>
<main>
<article class="help-article">
{article}
</article>
<aside class="related">
  <h3>Related articles</h3>
  <ul><li><a href="/help/returns">Returns</a></li><li><a href="/help/delivery">Delivery</a></li>
  <li><a href="/help/warranty">Warranty</a></li></ul>
</aside>
</main>
<footer class="site-footer">
  <p>&copy; 2025 ElectroStore. All rights reserved.</p>
  <ul><li><a href="/imprint">Imprint</a></li><li><a href="/privacy">Privacy</a></li><li><a href="/terms">Terms</a></li></ul>
  <p>Subscribe to our newsletter and get 5% off your next order!</p>
</footer>
<script src="/static/app.js"></script>
</body>
</html>
"""

# The old CMS: no semantic tags, layout tables, inline styles, a different menu.
LEGACY_TEMPLATE = """<html>
<head><meta http-equiv="Content-Type" content="text/html; charset=utf-8"><title>{title}</title></head>
<body bgcolor="#ffffff">
<div id="header"><table width="100%"><tr><td><img src="/img/logo.gif" alt="ElectroStore"></td>
<td><a href="/">HOME</a> | <a href="/shop">SHOP</a> | <a href="/help">HELP</a> | <a href="/login">LOGIN</a></td></tr></table></div>
<div class="cookie-notice" style="background:#eee">This site uses cookies. <a href="/cookies">More info</a></div>
<div id="content">
{article}
</div>
<div id="footer"><font size="1">ElectroStore &middot; Printed from the help centre &middot; Page generated by CMS v2.3</font></div>
</body>
</html>
"""


def render_html(blocks: list[tuple], path: Path, lang: str, legacy: bool = False) -> None:
    template = LEGACY_TEMPLATE if legacy else SITE_TEMPLATE
    page = template.format(lang=lang, title=_inline(title_of(blocks)), article=article_html(blocks))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")


# ---------------------------------------------------------------- build

def render(source_md: str, target: Path, lang: str = "en", legacy: bool = False) -> None:
    suffix = target.suffix.lower()
    if suffix == ".md":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source_md, encoding="utf-8")
        return
    blocks = parse_markdown(source_md)
    if suffix == ".docx":
        render_docx(blocks, target)
    elif suffix == ".html":
        render_html(blocks, target, lang, legacy)
    else:
        raise ValueError(f"cannot render {target}")


def derive(entry: dict, catalog: dict[str, dict], target: Path) -> None:
    spec = entry["derive"]
    kind = spec["kind"]
    target.parent.mkdir(parents=True, exist_ok=True)
    if kind == "legacy_template":
        render((AUTHORING / spec["from"]).read_text(encoding="utf-8"), target, legacy=True)
        return
    source = (RAW / spec["from"]).read_text(encoding="utf-8")
    if kind == "reformat":
        # Windows line endings, trailing spaces, a BOM and double spaces: the same content, other bytes.
        text = "﻿" + "\r\n".join(line.replace(". ", ".  ") + "  " for line in source.split("\n"))
        target.write_bytes(text.encode("utf-8"))
    elif kind == "edit":
        for old, new in spec["replace"].items():
            if old not in source:
                raise ValueError(f"{entry['path']}: '{old}' not found in {spec['from']}")
            source = source.replace(old, new)
        target.write_text(source, encoding="utf-8")
    else:
        raise ValueError(f"{entry['path']}: unknown derive kind {kind}")


def build_store() -> int:
    catalog = load_catalog()
    built = 0
    for path, entry in catalog.items():          # catalog order: sources come before their copies
        target = RAW / path
        if "authoring" in entry:
            render((AUTHORING / entry["authoring"]).read_text(encoding="utf-8"), target, entry["language"])
        elif "derive" in entry:
            derive(entry, catalog, target)
        else:
            continue
        built += 1
    print(f"built {built} store documents into {RAW.relative_to(RAW.parents[2])}")
    return built
