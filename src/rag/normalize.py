"""Normalization: one canonical text per document, so hashing, dedup and chunking all see the same thing."""

import re
import unicodedata

ZERO_WIDTH = re.compile("[​‌‍⁠﻿­]")   # zero-width chars, BOM, soft hyphen
INLINE_HTML = re.compile(r"</?(sup|sub|u|b|i|em|strong|span|br)\b[^>]*>", re.I)   # left by pymupdf4llm
PAGE_NUMBER = re.compile(r"^\s*((page|seite|сторінка)\s+)?\d{1,4}(\s*(of|/|von|з)\s*\d{1,4})?\s*$", re.I)
MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
BOLD_LINE = re.compile(r"^\*\*(.+?)\*\*$")
EDITORIAL_NOTE = re.compile(r"^\{[^{}]*\}$")
# zakon.rada.gov.ua editorial notes inside a paragraph: "{В редакції Закону № 3161-IV ...}".
# Curly braces do not occur in the other documents (markdown, legal text, manuals).
INLINE_EDITORIAL = re.compile(r"\s*\{[^{}]{0,1500}\}")
LINK_LINE = re.compile(r"^\s*<u>.*</u>\s*$")    # a line that is one hyperlink (PDF tables of contents)
EMPTY_PARENS = re.compile(r"\(\s*\)")            # what is left of a removed footnote marker: "Committee ( ),"
EDGE_LINES = 4      # lines at the top/bottom of a page that can be a running header or footer
EDGE_REPEAT = 0.25  # a line at a page edge on this share of pages is a running header/footer
# (not 50%: a manual's header is printed only on the first page of each topic, and topics span pages)

# Bold-only lines that are labels inside a section, not headings of their own.
LABELS = {"note", "hint", "related topic", "hinweis", "tipp", "verwandtes thema", "примітка"}
# "Related Topic" is followed by titles of other topics: links, not content. They would make a chunk
# about charging match a question about pairing, so the whole list is dropped.
RELATED = {"related topic", "verwandtes thema"}


def _plain(line: str) -> str:
    """A line without markdown decoration, for comparing headers and footers across pages."""
    return line.strip().lstrip("#").replace("**", "").strip()


def remove_running_lines(pages: list[list[str]]) -> list[list[str]]:
    """Drop lines that repeat at the top or bottom of most pages (running headers, footers, copyright)."""
    if len(pages) < 2:
        return pages
    counts: dict[str, int] = {}
    for lines in pages:
        content = [_plain(l) for l in lines if _plain(l)]
        for line in set(content[:EDGE_LINES] + content[-EDGE_LINES:]):
            counts[line] = counts.get(line, 0) + 1
    repeated = {line for line, n in counts.items() if n >= max(2, len(pages) * EDGE_REPEAT)}
    return [[l for l in lines if _plain(l) not in repeated] for lines in pages]


def remove_page_numbers(lines: list[str]) -> list[str]:
    """A bare number on the last lines of a page is a page number."""
    content_idx = [i for i, l in enumerate(lines) if l.strip()]
    tail = set(content_idx[-2:]) | set(content_idx[:1])
    return [l for i, l in enumerate(lines) if not (i in tail and PAGE_NUMBER.match(_plain(l) or "x"))]


def markdown_cleanup(line: str) -> str:
    """'# **Title**' -> '# Title'; a bold-only short line -> '### line'; other ** markers dropped."""
    m = MD_HEADING.match(line)
    if m:
        text = m.group(2).replace("**", "").strip()
        return f"{m.group(1)} {text}" if text else ""
    m = BOLD_LINE.match(line.strip())
    if m:
        inner = m.group(1).strip()
        is_heading = (len(inner) <= 80 and not inner.endswith((".", ":", ";", "!", "?", ","))
                      and not inner.replace(" ", "").isdigit() and inner.lower() not in LABELS)
        return f"### {inner}" if is_heading else inner
    return line.replace("**", "")


def is_structural(line: str) -> bool:
    s = line.lstrip()
    return bool(MD_HEADING.match(s)) or s.startswith(("- ", "|", "* ")) or bool(re.match(r"^\d+\.\s", s))


def unwrap(text: str) -> str:
    """Join lines a PDF broke inside a sentence. Headings, list items, table rows and short lines stay."""
    out: list[str] = []
    for line in text.split("\n"):
        prev = out[-1] if out else ""
        joinable = (prev.strip() and line.strip() and len(prev) >= 60
                    and not is_structural(line) and not MD_HEADING.match(prev.lstrip())
                    and not prev.lstrip().startswith("|")
                    and not prev.rstrip().endswith((".", ":", "!", "?", ";")))
        if joinable:
            out[-1] = f"{prev.rstrip()} {line.lstrip()}"
        else:
            out.append(line)
    return "\n".join(out)


def drop_related_lists(lines: list[str]) -> list[str]:
    """Remove a "Related Topic" label and the list of topic titles after it (until the next heading
    or a line long enough to be real text)."""
    out, skipping = [], False
    for line in lines:
        plain = _plain(line).lower()
        if plain in RELATED:
            skipping = True
            continue
        if skipping:
            if MD_HEADING.match(line.strip()) or len(line.strip()) > 90:
                skipping = False
            else:
                continue
        out.append(line)
    return out


def normalize(text: str) -> str:
    # 1. One unicode form, one line ending, no invisible characters, no links-only lines, no inline HTML.
    # NFKC would turn the Ukrainian "№" into "No"; keep it.
    text = unicodedata.normalize("NFKC", text.replace("№", "\x00")).replace("\x00", "№")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = INLINE_EDITORIAL.sub("", text)
    text = ZERO_WIDTH.sub("", text)
    text = "\n".join(l for l in text.split("\n") if not LINK_LINE.match(l))
    text = INLINE_HTML.sub("", text)
    text = EMPTY_PARENS.sub("", text)
    text = re.sub(r"[ \t]+([,.;:])", r"\1", text)

    # 2. Pages (PDF): running headers/footers and page numbers.
    pages = [page.split("\n") for page in text.split("\f")]
    pages = remove_running_lines(pages)
    pages = [remove_page_numbers(lines) for lines in pages]
    text = "\n\n".join("\n".join(lines).strip("\n") for lines in pages)

    # 3. Words hyphenated across lines: "Gewähr-\nleistung" -> "Gewährleistung".
    text = re.sub(r"(\w)-[ \t]*\n[ \t]*([a-zа-яіїєґäöüß])", r"\1\2", text)

    # 4. Markdown decoration, editorial notes, whitespace.
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        if EDITORIAL_NOTE.match(line):
            continue
        lines.append(markdown_cleanup(line))
    text = unwrap("\n".join(drop_related_lists(lines)))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
