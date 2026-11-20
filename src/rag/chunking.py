"""Chunking: structure-aware (the one we index) and fixed-size (the baseline we compare against).

Structure-aware: the document is a tree of markdown headings. Each section becomes one chunk if it fits
CHUNK_MAX_TOKENS; a longer section is split on its own boundaries (paragraphs, list items, table rows,
then sentences), and every piece repeats the section heading. A table piece repeats the header row.
Sibling sections smaller than CHUNK_MIN_TOKENS are merged, so a chunk is never just a heading.
Every chunk knows its heading path ("Rückgabe > Rücksendekosten"), which retrieval and citations use.
"""

import re
import statistics
from dataclasses import dataclass, field

import tiktoken

from .config import CHUNK_MAX_TOKENS, CHUNK_MIN_TOKENS, FIXED_OVERLAP, FIXED_TOKENS, TOKENIZER

ENC = tiktoken.get_encoding(TOKENIZER)
HEADING = re.compile(r"^(#{1,6})\s+(.+)$")
SENTENCE_END = re.compile(r"(?<=[.!?…])\s+(?=[\"„«(]?[A-ZА-ЯІЇЄҐÄÖÜ0-9])")


def n_tokens(text: str) -> int:
    return len(ENC.encode(text))


@dataclass
class Section:
    path: list[str]                                  # heading texts from the top: ["Title", "1. Строк"]
    heading_lines: list[str] = field(default_factory=list)   # markdown heading lines shown in the chunk
    blocks: list[str] = field(default_factory=list)


@dataclass
class Chunk:
    text: str
    paths: list[list[str]]       # heading path of every section in the chunk (several after a merge)

    @property
    def path(self) -> list[str]:
        return self.paths[0]

    @property
    def headings(self) -> list[str]:
        return list(dict.fromkeys(p[-1] for p in self.paths if p))

    @property
    def section(self) -> str:
        """The citation label. One section: its path. Merged sections: their common parent path, then the
        names of all merged sections: "Правила повернення > 1. Строк / 2. Як оформити / 3. Вартість"."""
        if len(self.paths) == 1:
            return " > ".join(self.path)
        prefix = self.paths[0]
        for p in self.paths[1:]:
            n = 0
            while n < min(len(prefix), len(p)) and prefix[n] == p[n]:
                n += 1
            prefix = prefix[:n]
        rest = list(dict.fromkeys(p[len(prefix)] for p in self.paths if len(p) > len(prefix)))
        return " > ".join(prefix + ([" / ".join(rest)] if rest else []))

    @property
    def tokens(self) -> int:
        return n_tokens(self.text)


# ---------------------------------------------------------------- parse

def sections_of(text: str) -> list[Section]:
    """Split markdown into sections. A heading with no body before the next heading is carried into
    the next section, so "# Title" + "## 1. Scope" + body gives one section showing both headings."""
    sections: list[Section] = []
    stack: list[tuple[int, str]] = []
    pending: list[str] = []            # heading lines waiting for a body
    current: Section | None = None

    for block in re.split(r"\n\s*\n", text):
        buf: list[str] = []
        for line in block.split("\n"):
            m = HEADING.match(line.strip())
            if not m:
                buf.append(line)
                continue
            if buf:
                current = _add_body(sections, current, stack, pending, "\n".join(buf))
                buf = []
            level, title = len(m.group(1)), m.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            pending.append(line.strip())
            current = None
        if buf and "\n".join(buf).strip():
            current = _add_body(sections, current, stack, pending, "\n".join(buf))
    if pending:   # trailing headings without a body: keep them, they still name the document's end
        sections.append(Section([t for _, t in stack], pending[:], []))
    return sections


def _add_body(sections, current, stack, pending, body):
    if current is None:
        current = Section([t for _, t in stack], pending[:], [])
        sections.append(current)
        pending.clear()
    current.blocks.append(body.strip())
    return current


# ---------------------------------------------------------------- split oversized blocks

def split_block(block: str, budget: int) -> list[str]:
    """A block that fits is returned whole. Otherwise split on natural boundaries only:
    a table by rows (each piece repeats the header), a list by items, prose by sentences."""
    if n_tokens(block) <= budget:
        return [block]
    lines = block.split("\n")
    header: list[str] = []
    if len(lines) > 1:
        if lines[0].startswith("|") and len(lines) > 2 and set(lines[1]) <= set("|-: "):
            header, lines = lines[:2], lines[2:]
        units, sep = lines, "\n"
    else:
        units, sep = SENTENCE_END.split(block), " "
    pieces: list[str] = []
    cur = list(header)
    for unit in units:
        if n_tokens(unit) > budget:
            # a giant list item or table row is split by sentences; a giant sentence by clauses/words
            if len(cur) > len(header):
                pieces.append(sep.join(cur))
                cur = list(header)
            pieces.extend(split_block(unit, budget) if sep == "\n" else _hard_split(unit, budget))
            continue
        if len(cur) > len(header) and n_tokens(sep.join(cur + [unit])) > budget:
            pieces.append(sep.join(cur))
            cur = list(header)
        cur.append(unit)
    if len(cur) > len(header):
        pieces.append(sep.join(cur))
    return pieces


def _hard_split(text: str, budget: int) -> list[str]:
    """Last resort for one sentence longer than the budget (German legal text has them):
    cut after a clause (; or ,) or at least between words, never inside a word."""
    pieces, cur = [], ""
    for part in re.split(r"(?<=[;,])\s+|\s+", text):
        candidate = f"{cur} {part}".strip()
        if cur and n_tokens(candidate) > budget:
            pieces.append(cur)
            cur = part
        else:
            cur = candidate
    if cur:
        pieces.append(cur)
    return pieces


# ---------------------------------------------------------------- structure-aware chunker

def chunk_structured(text: str, max_tokens: int = CHUNK_MAX_TOKENS, min_tokens: int = CHUNK_MIN_TOKENS,
                     merge_siblings: bool = True) -> list[Chunk]:
    """merge_siblings=False keeps every section apart (an FAQ: one question per chunk); a short intro still joins
    the first section under it."""
    chunks: list[Chunk] = []
    for sec in sections_of(text):
        head = "\n\n".join(sec.heading_lines)
        # the section's own heading is repeated in every piece; parent headings are in the path metadata
        own = sec.heading_lines[-1] if sec.heading_lines else ""
        budget = max(50, max_tokens - n_tokens(head) - 2)
        pieces = [p for b in sec.blocks for p in split_block(b, budget)]
        if not pieces:
            chunks.append(Chunk(head, [sec.path]))
            continue
        parts: list[str] = [head] if head else []
        has_body = False
        for piece in pieces:
            if has_body and n_tokens("\n\n".join(parts + [piece])) > max_tokens:
                chunks.append(Chunk("\n\n".join(parts), [sec.path]))
                parts, has_body = ([own] if own else []), False
            parts.append(piece)
            has_body = True
        chunks.append(Chunk("\n\n".join(parts), [sec.path]))
    return merge_small(chunks, max_tokens, min_tokens, merge_siblings)


def merge_small(chunks: list[Chunk], max_tokens: int, min_tokens: int, merge_siblings: bool = True) -> list[Chunk]:
    """Merge a chunk below min_tokens into its neighbour when both are siblings (same parent path)
    or the next one is its child, and the result still fits."""
    out: list[Chunk] = []
    for c in chunks:
        if out:
            prev = out[-1]
            small = prev.tokens < min_tokens or c.tokens < min_tokens
            anchor, last = prev.paths[0], prev.paths[-1]
            siblings = merge_siblings and len(last) == len(c.path) and last[:-1] == c.path[:-1]
            child = c.path[:len(anchor)] == anchor and len(c.path) > len(anchor)
            if not merge_siblings:   # only the intro takes its first section, not every section below it
                child = child and len(prev.paths) == 1
            if small and (siblings or child) and n_tokens(prev.text + "\n\n" + c.text) <= max_tokens:
                paths = prev.paths + [p for p in c.paths if p not in prev.paths]
                out[-1] = Chunk(prev.text + "\n\n" + c.text, paths)
                continue
        out.append(c)
    return out


# ---------------------------------------------------------------- fixed-size baseline

def heading_positions(text: str) -> list[tuple[int, str]]:
    """(char offset, heading path) for every heading: the fixed chunker uses it to label its chunks
    with the section where the chunk starts, so citations are comparable between the two strategies."""
    out, stack, offset = [], [], 0
    for line in text.split("\n"):
        m = HEADING.match(line.strip())
        if m:
            level = len(m.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, m.group(2).strip()))
            out.append((offset, [t for _, t in stack]))
        offset += len(line) + 1
    return out


def chunk_fixed(text: str, size: int = FIXED_TOKENS, overlap: int = FIXED_OVERLAP) -> list[tuple[Chunk, int]]:
    """A sliding window of tokens. Returns (chunk, start char offset)."""
    tokens = ENC.encode(text)
    if not tokens:
        return []
    _, offsets = ENC.decode_with_offsets(tokens)
    headings = heading_positions(text)
    out, start = [], 0
    while True:
        piece = ENC.decode(tokens[start:start + size])
        char_start = offsets[start]
        path = next((p for off, p in reversed(headings) if off <= char_start), [])
        out.append((Chunk(piece, [path]), char_start))
        if start + size >= len(tokens):
            break
        start += size - overlap
    return out


# ---------------------------------------------------------------- quality stats for the comparison

def is_table_cut(chunk_text: str) -> bool:
    """A chunk holds a broken table row, or table rows without the header separator."""
    lines = [l for l in chunk_text.strip().split("\n") if l.strip()]
    rows = [l for l in lines if l.lstrip().startswith("|") or l.rstrip().endswith("|")]
    if not rows:
        return False
    broken = any(not (r.strip().startswith("|") and r.strip().endswith("|")) for r in rows)
    headerless = not any(set(r.strip()) <= set("|-: ") for r in rows)
    return broken or headerless


def body_start(chunk_text: str) -> str:
    """The first line of a chunk that is not a heading (headings are repeated, not cut)."""
    for line in chunk_text.split("\n"):
        if line.strip() and not HEADING.match(line.strip()):
            return line.strip()
    return ""


def starts_clean(doc_text: str, chunk_text: str) -> bool:
    """Does the chunk's body begin where a line or a sentence of the document begins?
    The same test for both strategies: find the body's opening words in the document and look
    at what precedes them."""
    start = body_start(chunk_text)[:60]
    if not start:
        return True
    pos = doc_text.find(start)
    while pos != -1:
        before = doc_text[max(0, pos - 2):pos]
        if pos == 0 or before.endswith("\n") or re.search(r"[.!?…;:]\s$", before):
            return True
        pos = doc_text.find(start, pos + 1)
    return False


def chunk_stats(chunks: list[Chunk], starts_clean: list[bool]) -> dict:
    """starts_clean[i]: chunk i starts at a line or sentence start of the document."""
    sizes = [c.tokens for c in chunks] or [0]
    return {
        "chunks": len(chunks),
        "avg_tokens": round(sum(sizes) / len(sizes)),
        "median_tokens": int(statistics.median(sizes)),
        "max_tokens": max(sizes),
        "under_40_tokens": sum(s < 40 for s in sizes),
        "starts_mid_sentence": sum(not s for s in starts_clean),
        "ends_mid_sentence": sum(1 for c in chunks if c.text.rstrip()[-1:] not in ".!?:;)|»\"…" and not
                                 HEADING.match(c.text.strip().split("\n")[-1].strip())),
        "cut_tables": sum(is_table_cut(c.text) for c in chunks),
        "mixes_sections": sum(mixes_sections(c.text) for c in chunks),
    }


def mixes_sections(chunk_text: str) -> bool:
    """The chunk runs from the end of one section into the next: a heading appears after body text.
    (Merged tiny sibling sections count too: the metric is the same for both strategies.)"""
    seen_body = False
    for line in chunk_text.split("\n"):
        if not line.strip():
            continue
        if HEADING.match(line.strip()):
            if seen_body:
                return True
        else:
            seen_body = True
    return False
