"""Step 3: answer a question from the retrieved chunks, citing the document and section of every claim.

question -> retrieval (hybrid + rerank, current documents) -> "I don't know" gate on the reranker score
         -> context within a token budget -> Claude (JSON schema: claims, each with source id + exact quote)
         -> the code checks every quote against its chunk -> answer text + sources

A claim counts only when one of its quotes is found in the cited chunk; the section of the citation is the heading
the quote stands under, taken from the chunk text (not from the model).
"""

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field

from . import config as C
from .chunking import n_tokens
from .language import detect, detect_question
from .retrieve import Filters

LANG_NAMES = {"uk": "Ukrainian", "de": "German", "en": "English"}

TEXTS = {
    "uk": {"unknown": "Не знаю: у документах магазину немає відповіді на це питання.",
           "missing": "Немає в документах:", "sources": "Джерела:"},
    "de": {"unknown": "Das weiß ich nicht: Die Unterlagen des Shops beantworten diese Frage nicht.",
           "missing": "Nicht in den Unterlagen:", "sources": "Quellen:"},
    "en": {"unknown": "I don't know: the store documents do not answer this question.",
           "missing": "Not in the documents:", "sources": "Sources:"},
}

# Structured output. Constraints the schema cannot express (at least one source per claim, ids that exist,
# quotes that exist) are checked in validate().
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answerable": {"type": "boolean"},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "sources": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"id": {"type": "string"}, "quote": {"type": "string"}},
                            "required": ["id", "quote"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["text", "sources"],
                "additionalProperties": False,
            },
        },
        "missing": {"type": "string"},
    },
    "required": ["answerable", "claims", "missing"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------- data

@dataclass
class Citation:
    id: str            # S1, S2, ...
    chunk_id: str
    title: str
    section: str       # the heading the quote stands under
    quote: str


@dataclass
class Claim:
    text: str
    citations: list[Citation] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)   # sources the code could not verify: {id, quote, reason}


@dataclass
class Answer:
    question: str
    language: str
    answerable: bool
    text: str                       # what the customer sees: claims with citations, then the source list
    claims: list[Claim]             # verified claims
    dropped: list[Claim]            # claims without a single verified source (not shown)
    missing: str
    status: str                     # answered | not_found_retrieval | not_found_model | not_found_unverified | error
    context: list[dict]             # [{id, chunk_id, title, section, score, tokens}]
    context_tokens: int
    top_score: float | None
    prompt_version: str
    model: str
    input_tokens: int = 0           # all input, cached or not
    output_tokens: int = 0          # includes thinking
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    stop_reason: str | None = None
    error: str | None = None
    translations: dict = field(default_factory=dict)   # the question in uk / en / de, when QUERY_TRANSLATION is on
    retrieval_cost_usd: float = 0.0                     # the translation call (included in cost_usd)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- prompt and context

def load_prompt(version: str = C.PROMPT_VERSION) -> str:
    path = C.PROMPTS_DIR / f"{version}.md"
    if not path.exists():
        raise SystemExit(f"prompt {version} not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def question_language(question: str) -> str:
    if C.QUESTION_LANGUAGE == "v2":
        return detect_question(question) or "en"
    lang = detect(question)
    if lang in TEXTS:
        return lang
    return "uk" if re.search(r"[а-щьюяєіїґ]", question, re.I) else "en"


def build_context(hits: list[dict], budget: int = C.CONTEXT_BUDGET) -> tuple[list[dict], str, int]:
    """Number the hits S1..Sn in rank order and keep those that fit the budget. A hit that does not fit is skipped
    whole (a cut chunk could lose the condition of a rule); a smaller one after it may still fit."""
    used, blocks, total = [], [], 0
    for hit in hits:
        sid = f"S{len(used) + 1}"
        meta = (f"[{sid}] {hit['title']} | section: {hit['section']} | type: {hit['doc_type']} | "
                f"region: {hit['region']} | in force from: {hit.get('effective_date') or 'not stated'}")
        if hit.get("outdated_note"):
            meta += f" | note: {hit['outdated_note']}"
        block = f"{meta}\n{hit['text'].strip()}"
        tokens = n_tokens(block)
        if total + tokens > budget:
            continue
        used.append({"id": sid, "chunk": hit, "tokens": tokens})
        blocks.append(block)
        total += tokens
    return used, "\n\n".join(blocks), total


def demote_outdated_faq(hits: list[dict]) -> list[dict]:
    """An FAQ older than a store policy among the same hits (same region, or a policy for every region) goes to the end
    with a note. FAQs are not tied to a topic in the catalog, so they are not dropped: an FAQ may hold the only answer
    (no physical stores), but where an old FAQ and a newer policy give different numbers, the policy must win."""
    policies = [h for h in hits if h.get("doc_type") == "policy" and h.get("effective_date")]
    keep, moved = [], []
    for h in hits:
        if h.get("doc_type") == "faq" and h.get("effective_date"):
            newer = [p for p in policies if p["effective_date"] > h["effective_date"]
                     and (p["region"] == h["region"] or p["region"] == "INTL")]
            if newer:
                latest = max(p["effective_date"] for p in newer)
                moved.append({**h, "outdated_note": f"this FAQ (updated {h['effective_date']}) is older than the store "
                                                    f"policy in these sources (in force from {latest}); where they "
                                                    f"differ, the FAQ is outdated"})
                continue
        keep.append(h)
    return keep + moved


def user_message(question: str, language: str, context_text: str) -> str:
    return (f"<sources>\n{context_text}\n</sources>\n\n"
            f"Answer language: {LANG_NAMES[language]}\n\n"
            f"<question>\n{question}\n</question>")


# ---------------------------------------------------------------- checking the citations

def quote_pattern(quote: str) -> re.Pattern | None:
    """Whitespace- and case-insensitive match of the quote's words in order (line breaks in tables and PDFs)."""
    words = re.findall(r"\S+", quote.strip().strip("\"'«»„“”"))
    if not words:
        return None
    return re.compile(r"\s+".join(re.escape(w) for w in words), re.IGNORECASE)


def section_of(chunk: dict, position: int) -> str:
    """The heading the text at `position` stands under; the chunk's own label when no heading precedes it."""
    heading = None
    for m in re.finditer(r"^#{1,6}\s+(.+)$", chunk["text"], re.MULTILINE):
        if m.start() > position:
            break
        heading = m.group(1).strip()
    if heading is None or heading == chunk["title"]:
        return chunk["section"].split(" > ")[-1].split(" / ")[0] if chunk["section"] else chunk["title"]
    return heading


def validate(raw_claims: list[dict], context: list[dict]) -> tuple[list[Claim], list[Claim]]:
    by_id = {c["id"]: c["chunk"] for c in context}
    verified, dropped = [], []
    for raw in raw_claims:
        claim = Claim(text=raw.get("text", "").strip())
        for src in raw.get("sources", []):
            sid, quote = str(src.get("id", "")).strip().strip("[]"), src.get("quote", "")
            chunk = by_id.get(sid)
            if chunk is None:
                claim.rejected.append({"id": sid, "quote": quote, "reason": "no such source"})
                continue
            pattern = quote_pattern(quote)
            m = pattern.search(chunk["text"]) if pattern else None
            if m is None:
                claim.rejected.append({"id": sid, "quote": quote, "reason": "quote not in source"})
                continue
            claim.citations.append(Citation(sid, chunk["chunk_id"], chunk["title"], section_of(chunk, m.start()), quote))
        (verified if claim.citations and claim.text else dropped).append(claim)
    return verified, dropped


# ---------------------------------------------------------------- rendering

def label(c: Citation) -> str:
    return f"{c.title} › {c.section}"


def render(claims: list[Claim], missing: str, language: str) -> str:
    t = TEXTS[language]
    lines = []
    for claim in claims:
        refs = "; ".join(dict.fromkeys(label(c) for c in claim.citations))
        lines.append(f"{claim.text} [{refs}]")
    if missing:
        lines.append(f"{t['missing']} {missing}")
    sources = dict.fromkeys(label(c) for claim in claims for c in claim.citations)
    lines.append("")
    lines.append(t["sources"])
    lines += [f"- {s}" for s in sources]
    return "\n".join(lines)


# ---------------------------------------------------------------- the model

def make_client():
    import anthropic
    from dotenv import load_dotenv
    load_dotenv(C.ROOT / ".env")
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key or key == "your-key-here":
        raise SystemExit("ANTHROPIC_API_KEY is not set: copy .env.example to .env and add your key")
    return anthropic.Anthropic(api_key=key)


def cost(model: str, input_tokens: int, output_tokens: int, cache_write: int = 0, cache_read: int = 0) -> float:
    """USD. `input_tokens` is the uncached part; a cache write costs 1.25x the input price, a cache read 0.1x."""
    price_in, price_out = C.PRICE_PER_MTOK.get(model, (0.0, 0.0))
    return (input_tokens * price_in + cache_write * price_in * 1.25 + cache_read * price_in * 0.1
            + output_tokens * price_out) / 1_000_000


def call_model(client, system: str, user: str, model: str, effort: str | None) -> tuple[dict | None, object]:
    output_config = {"format": {"type": "json_schema", "schema": ANSWER_SCHEMA}}
    if effort:
        output_config["effort"] = effort
    # The system prompt is the same for every question: cache it (the question and its sources come after it).
    resp = client.messages.create(model=model, max_tokens=C.ANSWER_MAX_TOKENS,
                                  system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                                  messages=[{"role": "user", "content": user}], output_config=output_config)
    if resp.stop_reason != "end_turn":   # max_tokens (cut JSON) or refusal: nothing to trust
        return None, resp
    text = next((b.text for b in resp.content if b.type == "text"), "")
    return json.loads(text), resp


# ---------------------------------------------------------------- retrieval with translation

TRANSLATION_SCHEMA = {
    "type": "object",
    "properties": {"uk": {"type": "string"}, "en": {"type": "string"}, "de": {"type": "string"}},
    "required": ["uk", "en", "de"],
    "additionalProperties": False,
}


def _load_translation_cache() -> dict:
    if C.TRANSLATION_CACHE and C.TRANSLATION_CACHE.exists():
        return json.loads(C.TRANSLATION_CACHE.read_text(encoding="utf-8"))
    return {}


def translate(client, question: str) -> tuple[dict, float]:
    """The question in Ukrainian, English and German (normalized spelling), and the cost. {} when the call fails:
    retrieval then works with the question as it is.

    With TRANSLATION_CACHE set, a translation is reused for the same question and prompt version: the model's wording
    varies between calls, and so would the retrieved chunks, so evaluation runs would differ by chance. The cached cost
    is still reported, as a new question would pay it."""
    key = f"{C.QUERY_PROMPT_VERSION}::{question}"
    cache = _load_translation_cache()
    if key in cache:
        return cache[key]["translations"], cache[key]["cost_usd"]
    translations, spent = _translate(client, question)
    if translations and C.TRANSLATION_CACHE:
        cache = _load_translation_cache()
        cache[key] = {"translations": translations, "cost_usd": spent}
        C.TRANSLATION_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                                       encoding="utf-8")
    return translations, spent


def _translate(client, question: str) -> tuple[dict, float]:
    prompt = (C.QUERY_PROMPTS_DIR / f"{C.QUERY_PROMPT_VERSION}.md").read_text(encoding="utf-8").strip()
    try:
        resp = client.messages.create(
            model=C.ANSWER_MODEL, max_tokens=2000,
            system=[{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": question}],
            output_config={"format": {"type": "json_schema", "schema": TRANSLATION_SCHEMA}, "effort": "low"})
    except Exception:
        return {}, 0.0
    u = resp.usage
    spent = cost(C.ANSWER_MODEL, u.input_tokens, u.output_tokens, getattr(u, "cache_creation_input_tokens", 0) or 0,
                 getattr(u, "cache_read_input_tokens", 0) or 0)
    if resp.stop_reason != "end_turn":
        return {}, spent
    return json.loads(next(b.text for b in resp.content if b.type == "text")), spent


def retrieve(question: str, retriever, client=None, filters: Filters | None = None, **search_kw) -> dict:
    """{hits, translations, cost_usd}. With QUERY_TRANSLATION on, the question is translated first (one model call)."""
    translations, spent = {}, 0.0
    if C.QUERY_TRANSLATION:
        translations, spent = translate(client or make_client(), question)
    if translations:
        search_kw["translations"] = translations
    hits = retriever.search(question, mode="rerank", filters=filters, k=C.TOP_K, **search_kw)
    return {"hits": hits, "translations": translations, "cost_usd": spent}


# ---------------------------------------------------------------- one question

def answer(question: str, retriever, client=None, filters: Filters | None = None,
           prompt_version: str = C.PROMPT_VERSION, model: str = C.ANSWER_MODEL,
           effort: str | None = C.ANSWER_EFFORT, budget: int = C.CONTEXT_BUDGET,
           min_score: float = C.MIN_RERANK_SCORE, hits: list[dict] | None = None,
           translations: dict | None = None, retrieval_cost: float = 0.0) -> Answer:
    """`hits` (+ `translations`, `retrieval_cost`): already retrieved chunks; the evaluation retrieves once per question
    and answers several times."""
    started = time.perf_counter()
    language = question_language(question)
    t = TEXTS[language]
    system = load_prompt(prompt_version)
    if hits is None:
        got = retrieve(question, retriever, client, filters)
        hits, translations, retrieval_cost = got["hits"], got["translations"], got["cost_usd"]
    if C.CONTEXT_MIN_SCORE is not None:   # leave out hits that do not look relevant (fewer tokens, less noise)
        hits = [h for h in hits if h["score"] >= C.CONTEXT_MIN_SCORE] or hits[:1]
    top = hits[0]["score"] if hits else None
    if C.DEMOTE_OUTDATED_FAQ:   # after the threshold, which looks at the best score whatever its type
        hits = demote_outdated_faq(hits)
    context, context_text, context_tokens = build_context(hits, budget)
    ctx_info = [{"id": c["id"], "chunk_id": c["chunk"]["chunk_id"], "title": c["chunk"]["title"],
                 "section": c["chunk"]["section"], "score": round(c["chunk"]["score"], 3), "tokens": c["tokens"]}
                for c in context]
    result = Answer(question, language, False, t["unknown"], [], [], "", "not_found_retrieval", ctx_info,
                    context_tokens, top, prompt_version, model)
    result.translations, result.retrieval_cost_usd = translations or {}, retrieval_cost
    result.cost_usd = retrieval_cost

    if not context or top is None or top < min_score:
        result.latency_ms = int((time.perf_counter() - started) * 1000)
        return result

    client = client or make_client()
    try:
        data, resp = call_model(client, system, user_message(question, language, context_text), model, effort)
    except Exception as e:   # API or JSON error: report it, answer "I don't know" rather than guess
        result.status, result.error = "error", f"{type(e).__name__}: {e}"
        result.latency_ms = int((time.perf_counter() - started) * 1000)
        return result
    usage = resp.usage
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    result.input_tokens = usage.input_tokens + cache_write + cache_read
    result.output_tokens = usage.output_tokens
    result.cache_read_tokens = cache_read
    result.cost_usd = retrieval_cost + cost(model, usage.input_tokens, usage.output_tokens, cache_write, cache_read)
    result.stop_reason = resp.stop_reason
    result.latency_ms = int((time.perf_counter() - started) * 1000)
    if data is None:
        result.status, result.error = "error", f"stop_reason={resp.stop_reason}"
        return result

    verified, dropped = validate(data.get("claims", []), context)
    result.dropped = dropped
    if not data.get("answerable"):
        result.status = "not_found_model"
        return result
    if not verified:
        result.status = "not_found_unverified"
        return result
    result.answerable, result.status = True, "answered"
    result.claims, result.missing = verified, data.get("missing", "").strip()
    result.text = render(verified, result.missing, language)
    return result
