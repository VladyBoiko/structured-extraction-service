"""A small offline language check for uk / de / en.

The catalog declares each document's language; this check verifies it and measures how much of a
document is in another language (documents must be monolingual; mixed language is for questions only).
"""

import re

UK_ONLY = set("іїєґІЇЄҐ")
RU_ONLY = set("ыэёъЫЭЁЪ")
DE_WORDS = {"der", "die", "das", "und", "ist", "nicht", "mit", "für", "sie", "den", "dem", "ein", "eine",
            "auf", "zu", "von", "wird", "werden", "oder", "bei", "auch", "sich", "wenn", "nach", "des", "im"}
EN_WORDS = {"the", "and", "is", "not", "with", "for", "you", "your", "of", "to", "in", "on", "be", "are",
            "this", "that", "or", "by", "can", "from", "it", "if", "will", "as", "an", "at"}


def detect(text: str) -> str | None:
    """'uk' | 'ru' | 'de' | 'en', or None when there is too little text to tell."""
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 20:
        return None
    cyrillic = sum("Ѐ" <= c <= "ӿ" for c in letters) / len(letters)
    if cyrillic > 0.5:
        return "ru" if sum(c in RU_ONLY for c in text) > sum(c in UK_ONLY for c in text) else "uk"
    words = re.findall(r"[a-zäöüß]+", text.lower())
    de = sum(w in DE_WORDS for w in words) + 2 * len(re.findall(r"[äöüß]", text.lower()))
    en = sum(w in EN_WORDS for w in words)
    if de == en == 0:
        return None
    return "de" if de > en else "en"


def foreign_share(text: str, declared: str, min_chars: int = 80) -> float:
    """Share of the document's paragraphs (long enough to judge) detected as another language."""
    verdicts = [detect(p) for p in re.split(r"\n\s*\n", text) if len(p) >= min_chars and not p.startswith("|")]
    verdicts = [v for v in verdicts if v is not None]
    if not verdicts:
        return 0.0
    return round(sum(v != declared for v in verdicts) / len(verdicts), 3)
