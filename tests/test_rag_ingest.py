"""Offline tests for the RAG ingestion pipeline (block 2): no network, no API keys."""

from pathlib import Path

import pytest

from src.rag.build_store import parse_markdown, render
from src.rag.catalog import doc_id, load_catalog
from src.rag.chunking import (chunk_fixed, chunk_structured, is_table_cut, mixes_sections, n_tokens,
                              split_block, starts_clean)
from src.rag.config import AUTHORING, CHUNK_MAX_TOKENS
from src.rag.dedup import content_hash, near_duplicate_pairs
from src.rag.extract import extract
from src.rag.language import detect, foreign_share
from src.rag.normalize import normalize

POLICY_MD = """# Rückgabe

Version 2025.

## Rücksendekosten

| Land | Rücksendung |
|---|---|
| Deutschland | kostenlos |
| Österreich | 5,90 € |

## Ausnahmen

- In-Ear-Kopfhörer ohne Siegel;
- Geschenkkarten.

1. Melden Sie den Mangel.
2. Senden Sie das Gerät ein.
"""


# ---------------------------------------------------------------- catalog

def test_catalog_is_valid_and_complete():
    catalog = load_catalog()
    real = [e for e in catalog.values() if "derive" not in e]
    assert len(real) >= 50
    assert {e["language"] for e in real} == {"uk", "en", "de"}
    assert {Path(p).suffix for p in catalog} >= {".pdf", ".html", ".docx", ".md"}
    for e in real:
        if "authoring" in e:
            assert (AUTHORING / e["authoring"]).exists(), e["authoring"]
    assert len({doc_id(p) for p in catalog}) == len(catalog)
    superseded = [e for e in real if e["status"] == "superseded"]
    assert len(superseded) >= 3   # version traps: returns, delivery, loyalty


# ---------------------------------------------------------------- formats keep their structure

@pytest.mark.parametrize("suffix", [".md", ".docx", ".html"])
def test_every_format_keeps_headings_lists_and_tables(tmp_path, suffix):
    path = tmp_path / f"policy{suffix}"
    render(POLICY_MD, path, lang="de")
    text = normalize(extract(path).text)
    assert "# Rückgabe" in text
    assert "## Rücksendekosten" in text
    assert "| Österreich | 5,90 € |" in text
    assert "- Geschenkkarten." in text
    assert "1. Melden Sie den Mangel." in text
    if suffix == ".html":   # page chrome is gone
        for noise in ("cookies", "Related articles", "newsletter", "Sale %", "All rights reserved"):
            assert noise not in text


def test_same_text_in_two_html_templates_is_an_exact_duplicate(tmp_path):
    site, legacy = tmp_path / "a.html", tmp_path / "b.html"
    render(POLICY_MD, site, lang="de")
    render(POLICY_MD, legacy, lang="de", legacy=True)
    a, b = (normalize(extract(p).text) for p in (site, legacy))
    assert content_hash(a) == content_hash(b)


def test_eurlex_articles_become_headings(tmp_path):
    page = tmp_path / "eurlex.html"
    page.write_text("""<html><body><div class="eli-container">
      <p class="oj-ti-section-1">CHAPTER III</p><p class="oj-ti-section-2">CONSUMER INFORMATION</p>
      <p class="oj-ti-art">Article 9</p><p class="oj-sti-art">Right of withdrawal</p>
      <p class="oj-normal">The consumer shall have a period of 14 days<span class="oj-note-tag">(1)</span>.</p>
      <table><tr><td><p>(a)</p></td><td><p>in the case of sales contracts, the day on which the consumer acquires possession;</p></td></tr></table>
      <p class="oj-note">(1) OJ L 304, 22.11.2011.</p>
    </div></body></html>""", encoding="utf-8")
    text = normalize(extract(page).text)
    assert "## CHAPTER III — CONSUMER INFORMATION" in text
    assert "### Article 9 — Right of withdrawal" in text
    assert "- (a) in the case of sales contracts" in text   # a layout table is a list
    assert "OJ L 304" not in text and "(1)" not in text   # footnotes removed


def test_zakon_rada_articles_and_editorial_notes(tmp_path):
    page = tmp_path / "law.html"
    page.write_text("""<html><body><main>menu</main><div id="article">
      <p class="rvps7">Розділ II ПРАВА СПОЖИВАЧІВ</p>
      <p class="rvps2"><span class="rvts9">Стаття 8.</span> Права споживача у разі придбання товару неналежної якості</p>
      <p class="rvps2">1. У разі виявлення недоліків споживач має право вимагати заміни товару.</p>
      <p class="rvps2">{Частина перша статті 8 із змінами, внесеними згідно із Законом № 122-IX від 20.09.2019}</p>
    </div></body></html>""", encoding="utf-8")
    text = normalize(extract(page).text)
    assert "## Розділ II ПРАВА СПОЖИВАЧІВ" in text
    assert "### Стаття 8. Права споживача" in text
    assert "Із змінами" not in text and "{" not in text
    assert "menu" not in text


# ---------------------------------------------------------------- normalization

def test_pdf_running_headers_page_numbers_and_hyphenation():
    pages = []
    for i in range(1, 5):
        pages.append(f"Help Guide\nWireless Headset\n# **Topic {i}**\nBattery {i} lasts long and charging is quick-\nly done in {i} hours.\n"
                     f"5-048-298-11(7) Copyright 2023 Sony Corporation\n{i + 10}")
    text = normalize("\f".join(pages))
    assert "Help Guide" not in text and "Copyright" not in text
    assert "\n11\n" not in f"\n{text}\n"
    assert "# Topic 1" in text and "**" not in text
    assert "quickly done" in text


def test_related_topic_lists_and_link_lines_are_dropped():
    raw = ("# Charging\n\nCharge for 3 hours.\n\n**Related Topic**\n\nPairing the headset\n\nTurning off the headset\n\n"
           "<u>Checking the remaining battery charge</u>\n\n# Pairing\n\nHold the button.")
    text = normalize(raw)
    assert "Related Topic" not in text and "Turning off" not in text and "Checking the remaining" not in text
    assert "# Pairing" in text and "Hold the button." in text


def test_number_sign_and_unicode_cleanup():
    text = normalize("Закон № 1023-XII​, ста­ття")
    assert text == "Закон № 1023-XII, стаття"


# ---------------------------------------------------------------- dedup and language

def test_content_hash_ignores_whitespace_but_not_words():
    assert content_hash("a  b\r\nc ") == content_hash("a b\nc")
    assert content_hash("refund in 7 days") != content_hash("refund in 10 days")


def test_near_duplicates():
    base = " ".join(f"word{i}" for i in range(200))
    pairs = near_duplicate_pairs({"a": base, "b": base.replace("word5 ", "changed "), "c": "something else entirely"}, 0.8)
    assert [(a, b) for a, b, _ in pairs] == [("a", "b")]


@pytest.mark.parametrize("text,lang", [
    ("Товар можна повернути протягом 30 днів з дня отримання замовлення.", "uk"),
    ("Die Ware kann innerhalb von 30 Tagen zurückgegeben werden, wenn sie unbeschädigt ist.", "de"),
    ("The item can be returned within 30 days if it is complete and undamaged.", "en"),
])
def test_language_detection(text, lang):
    assert detect(text) == lang


def test_foreign_share():
    uk = "Товар можна повернути протягом 30 днів з дня отримання замовлення, якщо збережено упаковку."
    en = "The item can be returned within 30 days if it is complete and undamaged and in the box."
    assert foreign_share(f"{uk}\n\n{uk}\n\n{en}", "uk") == pytest.approx(1 / 3, abs=0.01)


# ---------------------------------------------------------------- chunking

def test_structured_chunks_follow_sections_and_respect_the_budget():
    chunks = chunk_structured(POLICY_MD.replace("Version 2025.", "Version 2025. " + "Lorem ipsum dolor sit. " * 10),
                              max_tokens=80, min_tokens=10)
    assert all(c.tokens <= 80 for c in chunks)
    sections = [c.section for c in chunks]
    assert "Rückgabe > Rücksendekosten" in sections
    table_chunk = next(c for c in chunks if "Österreich" in c.text)
    assert table_chunk.text.startswith("## Rücksendekosten")


def test_long_table_is_split_by_rows_with_the_header_repeated():
    table = "| Land | Preis |\n|---|---|\n" + "\n".join(f"| Land {i} | {i},90 € |" for i in range(60))
    pieces = split_block(table, 60)
    assert len(pieces) > 1
    for p in pieces:
        assert p.startswith("| Land | Preis |\n|---|---|")
        assert not is_table_cut(p)
        assert n_tokens(p) <= 60


def test_long_sentence_is_never_cut_inside_a_word():
    sentence = "Die Bestimmungen dieser Richtlinie gelten " + "für sehr lange Verträge, " * 80 + "und enden hier."
    pieces = split_block(sentence, 50)
    words = set(sentence.replace(",", "").split())
    for p in pieces:
        assert n_tokens(p) <= 50
        assert set(p.replace(",", "").split()) <= words


def test_small_sibling_sections_are_merged():
    md = "# FAQ\n\n## Q1\n\nYes.\n\n## Q2\n\nNo.\n\n## Q3\n\n" + "A long answer sentence here. " * 20
    chunks = chunk_structured(md, max_tokens=300, min_tokens=40)
    assert chunks[0].headings == ["Q1", "Q2"] or "Q1 / Q2" in chunks[0].section
    assert all(c.tokens >= 10 for c in chunks)


def test_merged_chunk_names_every_section_it_holds():
    """The section label is the citation: after a merge it must name all merged sections."""
    md = "# Returns\n\nVersion 2025.\n\n## 1. Window\n\n30 days.\n\n## 2. How\n\nUse the form.\n\n## 3. Cost\n\nFree."
    chunks = chunk_structured(md, max_tokens=300, min_tokens=150)
    assert len(chunks) == 1
    assert chunks[0].section == "Returns > 1. Window / 2. How / 3. Cost"


def test_fixed_chunks_overlap_and_cut_mid_sentence():
    text = "# Policy\n\n" + " ".join(f"Sentence number {i} explains a rule." for i in range(200))
    chunks = chunk_fixed(text, size=100, overlap=20)
    assert len(chunks) > 5
    assert all(c.tokens <= 100 for c, _ in chunks)
    assert chunks[1][0].path == ["Policy"]
    clean = [starts_clean(text, c.text) for c, _ in chunks[1:]]
    assert not all(clean)


def test_quality_metrics():
    assert is_table_cut("| a | b |\n| 1 | 2 |")               # rows without the header separator
    assert not is_table_cut("| a | b |\n|---|---|\n| 1 | 2 |")
    assert mixes_sections("text of one section\n\n## Next section\n\nmore")
    assert not mixes_sections("## Section\n\nbody only")
    doc = "# T\n\nFirst sentence. Second sentence here."
    assert starts_clean(doc, "Second sentence here.")
    assert not starts_clean(doc, "sentence here.")


def test_authoring_markdown_parser():
    blocks = parse_markdown(POLICY_MD)
    kinds = [b[0] for b in blocks]
    assert kinds == ["h", "p", "h", "table", "h", "ul", "ol"]
    assert blocks[3][1][0] == ["Land", "Rücksendung"]


def test_real_chunks_file_if_built():
    """When the corpus has been ingested, the committed chunks must respect the contract."""
    import json
    from src.rag.config import CHUNKS
    if not CHUNKS.exists():
        pytest.skip("run `python -m src.rag data` first")
    records = [json.loads(l) for l in CHUNKS.read_text(encoding="utf-8").splitlines()]
    ids = [r["chunk_id"] for r in records]
    assert len(ids) == len(set(ids))
    for r in records:
        assert r["n_tokens"] <= CHUNK_MAX_TOKENS
        for key in ("source", "title", "section", "language", "region", "version", "status", "doc_hash", "doc_type"):
            assert key in r
    assert {r["status"] for r in records} == {"current", "superseded"}


def test_faq_per_question_keeps_every_question_apart():
    md = "# FAQ\n\nUpdated 2025.\n\n## Q1?\n\nYes.\n\n## Q2?\n\nNo.\n\n## Q3?\n\nMaybe."
    merged = chunk_structured(md, max_tokens=300, min_tokens=150)
    apart = chunk_structured(md, max_tokens=300, min_tokens=150, merge_siblings=False)
    assert len(merged) == 1
    assert [c.section for c in apart] == ["FAQ > Q1?", "FAQ > Q2?", "FAQ > Q3?"]
    assert apart[0].text.startswith("# FAQ")        # the intro joins the first question
