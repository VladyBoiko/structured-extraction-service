"""Text extraction that keeps the structure: every format becomes markdown with headings, lists and tables.

    PDF   pymupdf4llm (font-size headings, real tables); pages separated by \\f for header/footer removal
    HTML  boilerplate removed, the content root found, blocks walked in order; site rules for
          EUR-Lex (articles), zakon.rada.gov.ua (статті, editorial notes) and gesetze-im-internet.de
    DOCX  the body walked in order: Title/Heading styles, numbered and bulleted lists, tables
    MD    read with encoding detection
"""

import re
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag
from charset_normalizer import from_bytes

from .config import MIN_CHARS_PER_PAGE


@dataclass
class Extracted:
    text: str                 # markdown; PDF pages separated by \f
    needs_ocr: bool = False   # a scan without a text layer: flagged, not indexed
    title_hint: str = ""      # title from the file's own metadata, if any


def collapse(text: str) -> str:
    return " ".join(text.split())


# ---------------------------------------------------------------- text files

def read_text_file(path: Path) -> str:
    data = path.read_bytes()
    best = from_bytes(data).best()
    text = str(best) if best is not None else data.decode("utf-8", errors="replace")
    return text.lstrip("﻿")


# ---------------------------------------------------------------- PDF

def extract_pdf(path: Path) -> Extracted:
    import pymupdf
    import pymupdf4llm

    # The classic engine: headings from font sizes, tables as markdown. The layout model is 5x slower
    # on the 180-page manuals and gives no better structure for these documents.
    pymupdf4llm.use_layout(False)
    pages = pymupdf4llm.to_markdown(str(path), page_chunks=True, ignore_images=True, show_progress=False)
    texts = [p["text"] for p in pages]
    n_chars = len("".join("".join(texts).split()))
    needs_ocr = n_chars < MIN_CHARS_PER_PAGE * max(1, len(texts))
    with pymupdf.open(path) as doc:
        title = (doc.metadata or {}).get("title") or ""
    return Extracted("\f".join(texts), needs_ocr, title.strip())


# ---------------------------------------------------------------- DOCX

def extract_docx(path: Path) -> Extracted:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(path)
    blocks: list[tuple[str, str]] = []   # (kind, markdown) in document order
    list_no = 0
    for el in doc.element.body.iterchildren():
        tag = el.tag.split("}")[-1]
        if tag == "tbl":
            list_no = 0
            rows = [[collapse(c.text).replace("|", "\\|") for c in row.cells] for row in Table(el, doc).rows]
            if rows:
                lines = ["| " + " | ".join(r) + " |" for r in rows]
                lines.insert(1, "|" + "---|" * len(rows[0]))
                blocks.append(("table", "\n".join(lines)))
            continue
        if tag != "p":
            continue
        p = Paragraph(el, doc)
        text = collapse(p.text)
        if not text:
            continue
        style = p.style.name if p.style is not None else ""
        if style.startswith("List Number"):
            list_no += 1
            blocks.append(("list", f"{list_no}. {text}"))
            continue
        list_no = 0
        if style == "Title":
            blocks.append(("heading", "# " + text))
        elif style.startswith("Heading"):
            level = int(style.split()[-1]) if style.split()[-1].isdigit() else 1
            blocks.append(("heading", "#" * min(level + 1, 6) + " " + text))
        elif style.startswith("List"):
            blocks.append(("list", "- " + text))
        else:
            blocks.append(("text", text))
    title = doc.core_properties.title or ""
    return Extracted(join_blocks(blocks), False, title)


def join_blocks(blocks: list[tuple[str, str]]) -> str:
    """Blank line between blocks; items of one list stay together."""
    if not blocks:
        return ""
    out = blocks[0][1]
    for (prev, _), (kind, text) in zip(blocks, blocks[1:]):
        out += ("\n" if prev == kind == "list" else "\n\n") + text
    return out


# ---------------------------------------------------------------- HTML

BOILERPLATE_TAGS = ["script", "style", "noscript", "nav", "header", "footer", "aside", "form", "button",
                    "iframe", "svg", "select", "input", "label", "img", "link", "meta"]
BOILERPLATE_SELECTORS = [
    '[id*="cookie"]', '[class*="cookie"]', '[class*="breadcrumb"]', '[class*="newsletter"]',
    "#header", "#footer", ".site-header", ".site-footer",
    "span.oj-note-tag", "p.oj-note", "p.note",           # EUR-Lex footnote markers and footnotes
    "div.jnheader > a",                                   # gesetze-im-internet: "Nichtamtliches Inhaltsverzeichnis"
]
# The first selector that matches is the content root.
ROOT_SELECTORS = ["div#article", "div.eli-container", "main article", "article", "main", "div#content"]

BLOCK_TAGS = {"p", "div", "section", "article", "main", "table", "ul", "ol", "dl", "li", "dd", "dt",
              "blockquote", "pre", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "tbody", "thead", "tr", "center"}

# Site rules: paragraphs that are really headings.
EURLEX_HEADING = {"oj-ti-section-1": 2, "ti-section-1": 2, "oj-ti-art": 3, "ti-art": 3}
EURLEX_SUBTITLE = {"oj-ti-section-2", "ti-section-2", "oj-sti-art", "sti-art"}   # second line of a heading
UA_SECTION = re.compile(r"^Розділ\s+[IVXLC]+\b")
UA_ARTICLE = re.compile(r"^Стаття\s+\d+(\s*[-–]\s*\d+)?\.")
EDITORIAL_NOTE = re.compile(r"^\{.*\}$", re.S)      # zakon.rada.gov.ua: "{Із змінами, внесеними згідно ...}"


def find_root(soup: BeautifulSoup) -> Tag:
    gesetze = soup.select_one("div.jnheader")
    if gesetze is not None:
        return gesetze.parent
    for selector in ROOT_SELECTORS:
        root = soup.select_one(selector)
        if root is not None:
            return root
    return soup.body or soup


class HtmlWalker:
    """Walks the content root in document order and emits markdown blocks."""

    def __init__(self):
        self.blocks: list[tuple[str, str]] = []   # (kind, markdown)

    def emit(self, kind: str, text: str) -> None:
        text = text.strip()
        if text:
            self.blocks.append((kind, text))

    def heading(self, level: int, text: str) -> None:
        self.emit("heading", "#" * level + " " + collapse(text))

    def extend_heading(self, text: str) -> None:
        """EUR-Lex splits a heading in two lines: "Article 9" + "Right of withdrawal"."""
        if self.blocks and self.blocks[-1][0] == "heading":
            self.blocks[-1] = ("heading", f"{self.blocks[-1][1]} — {collapse(text)}")
        else:
            self.emit("text", collapse(text))

    def paragraph(self, el: Tag, text: str) -> None:
        classes = set(el.get("class") or [])
        if EDITORIAL_NOTE.match(text):
            return
        for cls, level in EURLEX_HEADING.items():
            if cls in classes:
                return self.heading(level, text)
        if classes & EURLEX_SUBTITLE:
            return self.extend_heading(text)
        if UA_SECTION.match(text):
            return self.heading(2, text)
        if UA_ARTICLE.match(text):
            return self.heading(3, text)
        self.emit("text", text)

    def table(self, el: Tag) -> None:
        rows = []
        for tr in el.find_all("tr"):
            if tr.find_parent("table") is not el:
                continue  # rows of a nested table belong to the cell text
            cells = [collapse(td.get_text(" ")) for td in tr.find_all(["td", "th"], recursive=False)]
            if any(cells):
                rows.append(cells)
        if not rows:
            return
        # EUR-Lex lays out numbered points as 2-column tables: "(a)" | text. These are lists, not tables.
        if all(len(r) == 2 and len(r[0]) <= 6 for r in rows):
            self.emit("list", "\n".join(f"- {a} {b}".rstrip() for a, b in rows))
            return
        width = max(len(r) for r in rows)
        if width == 1:   # a one-cell "table" is layout (zakon.rada puts the law's name in one)
            for r in rows:
                self.emit("text", r[0])
            return
        lines =["| " + " | ".join(c.replace("|", "\\|") for c in r + [""] * (width - len(r))) + " |" for r in rows]
        lines.insert(1, "|" + "---|" * width)
        self.emit("table", "\n".join(lines))

    def walk(self, el: Tag) -> None:
        inline: list[str] = []

        def flush() -> None:
            text = collapse(" ".join(inline))
            inline.clear()
            if text:
                self.paragraph(el, text)

        for child in el.children:
            if isinstance(child, NavigableString):
                if type(child) is NavigableString:   # skip comments, CDATA, doctype
                    inline.append(str(child))
                continue
            if not isinstance(child, Tag):
                continue
            name = child.name
            if name not in BLOCK_TAGS:
                inline.append(child.get_text(" "))
                continue
            flush()
            if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                self.heading(int(name[1]), child.get_text(" "))
            elif name == "table":
                self.table(child)
            elif name in ("ul", "ol"):
                items = [collapse(li.get_text(" ")) for li in child.find_all("li", recursive=False)]
                marker = (lambda i: f"{i}.") if name == "ol" else (lambda i: "-")
                self.emit("list", "\n".join(f"{marker(i)} {t}" for i, t in enumerate(items, 1) if t))
            elif name == "dl":
                terms = child.find_all(["dt", "dd"], recursive=False)
                items, term = [], ""
                for t in terms:
                    if t.name == "dt":
                        term = collapse(t.get_text(" "))
                    else:
                        items.append(f"- {term} {collapse(t.get_text(' '))}".replace("-  ", "- "))
                self.emit("list", "\n".join(items))
            elif name == "hr":
                continue
            elif name == "p" or not any(isinstance(c, Tag) and c.name in BLOCK_TAGS for c in child.children):
                self.paragraph(child, collapse(child.get_text(" ")))
            else:
                self.walk(child)
        flush()


def extract_html(path: Path) -> Extracted:
    soup = BeautifulSoup(read_text_file(path), "html.parser")
    title = collapse(soup.title.get_text()) if soup.title else ""
    for tag in soup(BOILERPLATE_TAGS):
        tag.decompose()
    for selector in BOILERPLATE_SELECTORS:
        for tag in soup.select(selector):
            tag.decompose()
    walker = HtmlWalker()
    walker.walk(find_root(soup))
    return Extracted(join_blocks(walker.blocks), False, title)


# ---------------------------------------------------------------- dispatch

def extract(path: Path) -> Extracted:
    suffix = path.suffix.lower()
    if suffix in (".md", ".txt"):
        return Extracted(read_text_file(path))
    if suffix in (".html", ".htm"):
        return extract_html(path)
    if suffix == ".pdf":
        return extract_pdf(path)
    if suffix == ".docx":
        return extract_docx(path)
    raise ValueError(f"unsupported file type: {suffix}")
