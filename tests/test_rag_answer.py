"""Offline tests for the answer step (block 2, step 3): a fake retriever and a fake Claude client, no API calls."""

import json
from types import SimpleNamespace

import pytest

from src.rag import config as C
from src.rag.answer import (ANSWER_SCHEMA, answer, build_context, load_prompt, question_language, render,
                            section_of, validate)

@pytest.fixture(autouse=True)
def base_switches(monkeypatch):
    """The tests do not depend on the switches in config.py: every fix is off unless a test turns it on."""
    monkeypatch.setattr(C, "QUESTION_LANGUAGE", "v1")
    monkeypatch.setattr(C, "QUERY_TRANSLATION", False)
    monkeypatch.setattr(C, "CONTEXT_MIN_SCORE", None)
    monkeypatch.setattr(C, "DEMOTE_OUTDATED_FAQ", False)
    monkeypatch.setattr(C, "TRANSLATION_CACHE", None)


RETURNS = {
    "chunk_id": "returns_ua_2025#000", "doc_id": "returns_ua_2025", "title": "Правила повернення товару (Україна)",
    "section": "Правила повернення товару (Україна) > 1. Строк повернення / 3. Вартість доставки повернення",
    "doc_type": "policy", "region": "UA", "effective_date": "2025-03-01", "score": 3.4,
    "text": "# Правила повернення товару (Україна)\n\nВерсія 2025.\n\n## 1. Строк повернення\n\nЕлектроСтор подовжив "
            "строк повернення\nтовару належної якості до 30 днів з дня отримання.\n\n## 3. Вартість доставки повернення"
            "\n\n| Сума | Хто платить |\n|---|---|\n| від 1 500 грн | ElectroStore |",
}
FAQ = {
    "chunk_id": "faq_ua#000", "doc_id": "faq_ua", "title": "Часті запитання", "section": "Часті запитання > Повернення",
    "doc_type": "faq", "region": "UA", "effective_date": "2024-05-10", "score": 2.9,
    "text": "## Скільки днів я маю на повернення товару?\n\nПовернути товар можна протягом 14 днів.",
}


class FakeRetriever:
    def __init__(self, hits):
        self.hits = hits
        self.calls = 0

    def search(self, query, mode="rerank", filters=None, k=5):
        self.calls += 1
        return [dict(h, rank=i + 1) for i, h in enumerate(self.hits)]


class FakeClient:
    """Returns a fixed JSON answer and records the request."""

    def __init__(self, data, stop_reason="end_turn"):
        self.data, self.stop_reason, self.requests = data, stop_reason, []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(stop_reason=self.stop_reason,
                               content=[SimpleNamespace(type="text", text=json.dumps(self.data, ensure_ascii=False))],
                               usage=SimpleNamespace(input_tokens=3000, output_tokens=200))


def ctx(*hits):
    used, _, _ = build_context(list(hits))
    return used


# ---------------------------------------------------------------- context budget

def test_context_is_numbered_in_rank_order_and_keeps_the_budget():
    used, text, tokens = build_context([RETURNS, FAQ], budget=10_000)
    assert [u["id"] for u in used] == ["S1", "S2"]
    assert text.startswith("[S1] Правила повернення товару (Україна)")
    assert "type: faq" in text and "in force from: 2024-05-10" in text
    assert tokens == sum(u["tokens"] for u in used)


def test_a_chunk_that_does_not_fit_is_skipped_whole():
    big = dict(FAQ, chunk_id="big#000", text="слово " * 3000)
    used, text, tokens = build_context([RETURNS, big, FAQ], budget=400)
    assert [u["chunk"]["chunk_id"] for u in used] == ["returns_ua_2025#000", "faq_ua#000"]
    assert [u["id"] for u in used] == ["S1", "S2"]     # ids stay consecutive
    assert tokens <= 400 and "слово слово" not in text


# ---------------------------------------------------------------- citations are checked by code

def test_quote_found_across_a_line_break_and_section_is_the_heading_above_it():
    claims, dropped = validate([{"text": "30 днів.", "sources": [
        {"id": "S1", "quote": "строк повернення товару належної якості до 30 днів"}]}], ctx(RETURNS))
    assert not dropped
    cite = claims[0].citations[0]
    assert cite.chunk_id == "returns_ua_2025#000"
    assert cite.section == "1. Строк повернення"          # not the merged label of the whole chunk


def test_quote_in_a_table_gets_its_own_section():
    claims, _ = validate([{"text": "Безкоштовно від 1 500 грн.", "sources": [
        {"id": "S1", "quote": "від 1 500 грн | ElectroStore"}]}], ctx(RETURNS))
    assert claims[0].citations[0].section == "3. Вартість доставки повернення"


def test_invented_quote_or_unknown_source_is_rejected():
    claims, dropped = validate([
        {"text": "60 днів.", "sources": [{"id": "S1", "quote": "до 60 днів"}]},
        {"text": "30 днів.", "sources": [{"id": "S7", "quote": "до 30 днів"}]},
        {"text": "Без джерела.", "sources": []},
    ], ctx(RETURNS))
    assert claims == []
    assert [d.rejected[0]["reason"] if d.rejected else None for d in dropped] == \
        ["quote not in source", "no such source", None]


def test_a_quote_from_the_wrong_source_does_not_count():
    claims, dropped = validate([{"text": "14 днів.", "sources": [
        {"id": "S1", "quote": "протягом 14 днів"}]}], ctx(RETURNS, FAQ))
    assert claims == [] and dropped[0].rejected[0]["reason"] == "quote not in source"


# ---------------------------------------------------------------- the whole step

def test_answer_with_verified_citations():
    client = FakeClient({"answerable": True, "missing": "", "claims": [
        {"text": "Повернути товар можна протягом 30 днів.",
         "sources": [{"id": "S1", "quote": "до 30 днів з дня отримання"}]}]})
    res = answer("Скільки днів на повернення?", FakeRetriever([RETURNS, FAQ]), client=client)
    assert res.status == "answered" and res.answerable
    assert res.text.startswith("Повернути товар можна протягом 30 днів. [Правила повернення товару (Україна) › 1. Строк повернення]")
    assert "Джерела:" in res.text
    assert res.prompt_version == C.PROMPT_VERSION and res.model == C.ANSWER_MODEL
    assert res.cost_usd > 0 and res.input_tokens == 3000
    req = client.requests[0]
    assert req["model"] == C.ANSWER_MODEL
    assert req["output_config"]["format"]["schema"] == ANSWER_SCHEMA
    assert req["system"][0]["text"] == load_prompt() and req["system"][0]["cache_control"]["type"] == "ephemeral"
    assert "Answer language: Ukrainian" in req["messages"][0]["content"]


def test_nothing_relevant_found_means_no_model_call():
    client = FakeClient({})
    res = answer("Яка погода завтра?", FakeRetriever([dict(FAQ, score=-9.0)]), client=client)
    assert res.status == "not_found_retrieval" and not res.answerable
    assert res.text.startswith("Не знаю")
    assert client.requests == [] and res.cost_usd == 0


def test_model_says_not_answerable():
    client = FakeClient({"answerable": False, "missing": "", "claims": []})
    res = answer("What happens to my instalment plan?", FakeRetriever([RETURNS]), client=client)
    assert res.status == "not_found_model" and res.text.startswith("I don't know")


def test_answer_without_a_single_verified_claim_is_i_dont_know():
    client = FakeClient({"answerable": True, "missing": "", "claims": [
        {"text": "60 днів.", "sources": [{"id": "S1", "quote": "до 60 днів"}]}]})
    res = answer("Скільки днів на повернення?", FakeRetriever([RETURNS]), client=client)
    assert res.status == "not_found_unverified" and res.text.startswith("Не знаю")
    assert res.dropped[0].text == "60 днів."


def test_cut_or_refused_answer_is_not_used():
    client = FakeClient({"answerable": True, "claims": [], "missing": ""}, stop_reason="max_tokens")
    res = answer("Скільки днів на повернення?", FakeRetriever([RETURNS]), client=client)
    assert res.status == "error" and "max_tokens" in res.error and res.text.startswith("Не знаю")


def test_partial_answer_names_what_is_missing():
    claims, _ = validate([{"text": "30 днів.", "sources": [{"id": "S1", "quote": "до 30 днів"}]}], ctx(RETURNS))
    text = render(claims, "Хто платить за повернення великої техніки.", "uk")
    assert "Немає в документах: Хто платить" in text


def test_question_language():
    assert question_language("Wer zahlt den Zoll bei einer Lieferung in die Schweiz?") == "de"
    assert question_language("Do you deliver to London?") == "en"
    assert question_language("Можна оплатити частинами order на 1000 грн?") == "uk"


def test_section_without_a_heading_falls_back_to_the_chunk_label():
    chunk = dict(FAQ, text="Повернути товар можна протягом 14 днів.")
    assert section_of(chunk, 0) == "Повернення"


def test_question_language_v2_handles_short_and_transliterated_questions(monkeypatch):
    monkeypatch.setattr(C, "QUESTION_LANGUAGE", "v2")
    assert question_language("Gibt es Trade-in in Deutschland?") == "de"
    assert question_language("skilky koshtuye dostavka na viddilennya NP?") == "uk"
    assert question_language("Can I pay in instalments in Germany?") == "en"
    assert question_language("Tracking number?") == "en"                 # nothing to tell: English


def test_translation_goes_to_the_search_and_its_cost_to_the_answer(monkeypatch):
    from src.rag import answer as A
    monkeypatch.setattr(C, "QUERY_TRANSLATION", True)
    monkeypatch.setattr(A, "translate", lambda client, q: ({"uk": "q uk", "en": "q en", "de": "q de"}, 0.0001))
    seen = {}

    class Recording(FakeRetriever):
        def search(self, query, mode="rerank", filters=None, k=5, **kw):
            seen.update(kw)
            return super().search(query, mode, filters, k)

    client = FakeClient({"answerable": True, "missing": "", "claims": [
        {"text": "30 днів.", "sources": [{"id": "S1", "quote": "до 30 днів з дня отримання"}]}]})
    res = answer("Скільки днів на повернення?", Recording([RETURNS]), client=client)
    assert seen["translations"]["en"] == "q en"
    assert res.translations["de"] == "q de" and res.retrieval_cost_usd == 0.0001
    assert res.cost_usd > res.retrieval_cost_usd


def test_context_filter_leaves_out_low_scores(monkeypatch):
    monkeypatch.setattr(C, "CONTEXT_MIN_SCORE", 0.0)
    client = FakeClient({"answerable": True, "missing": "", "claims": [
        {"text": "30 днів.", "sources": [{"id": "S1", "quote": "до 30 днів з дня отримання"}]}]})
    res = answer("Скільки днів на повернення?", FakeRetriever([RETURNS, dict(FAQ, score=-2.0)]), client=client)
    assert [c["chunk_id"] for c in res.context] == ["returns_ua_2025#000"]


def test_an_faq_older_than_a_policy_goes_last_with_a_note():
    from src.rag.answer import demote_outdated_faq
    policy = dict(RETURNS, chunk_id="delivery_ua_2025#000", doc_type="policy", region="UA", effective_date="2025-06-01")
    old_faq = dict(FAQ, region="UA", effective_date="2024-05-10", score=6.6)
    other_region = dict(FAQ, chunk_id="faq_dach#004", region="DACH", effective_date="2024-05-10")
    hits = demote_outdated_faq([old_faq, policy, other_region])
    assert [h["chunk_id"] for h in hits] == ["delivery_ua_2025#000", "faq_dach#004", "faq_ua#000"]
    assert "older than the store policy" in hits[-1]["outdated_note"] and "outdated_note" not in hits[1]
    used, text, _ = build_context(hits, budget=10_000)
    assert "note: this FAQ (updated 2024-05-10)" in text
    # no newer policy in the context: the FAQ stays where it is, untouched (it may hold the only answer)
    assert demote_outdated_faq([old_faq]) == [old_faq]


def test_translation_cache_reuses_the_same_translation(monkeypatch, tmp_path):
    from src.rag import answer as A
    monkeypatch.setattr(C, "TRANSLATION_CACHE", tmp_path / "translations.json")
    calls = []
    monkeypatch.setattr(A, "_translate", lambda client, q: (calls.append(q) or {"uk": f"uk {len(calls)}"}, 0.0001))
    first = A.translate(None, "Питання?")
    second = A.translate(None, "Питання?")
    assert first == second == ({"uk": "uk 1"}, 0.0001) and calls == ["Питання?"]
    assert A.translate(None, "Інше?")[0] == {"uk": "uk 2"}
