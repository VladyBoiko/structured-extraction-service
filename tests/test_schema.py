import json
import re
from pathlib import Path

from src.pipeline import load_golden, load_texts
from src.schema import Category, TicketExtraction, json_schema

DATA = Path(__file__).resolve().parent.parent / "data"


def test_schema_meets_assignment_requirements():
    s = json_schema()
    props = s["properties"]
    assert len(props) >= 6
    assert any("enum" in p for p in props.values())                    # has an enum
    assert props["products"]["items"]["type"] == "object"              # has nested objects
    assert "$ref" not in json.dumps(s)                                 # schema is self-contained


def test_golden_labels_match_schema():
    for gid, g in load_golden(DATA / "golden").items():
        label = TicketExtraction.model_validate(g)                     # full schema, nothing filled in
        oid = label.order_id
        assert oid is None or re.fullmatch(r"ES-\d{5}", oid), gid


def test_dataset_size_and_coverage():
    texts = load_texts(DATA / "texts")
    labels = load_golden(DATA / "golden")
    ids = {t["id"] for t in texts}
    assert len(texts) >= 75 and all(t["text"].strip() for t in texts)
    assert len(labels) >= 30 and set(labels) <= ids                    # every label has its text
    assert {g["category"] for g in labels.values()} == {c.value for c in Category}  # every category is labeled
    assert any(len(g["products"]) > 1 for g in labels.values())
    for field in ("escalation_threat", "repeat_contact", "deadline", "tracking_number"):
        assert any(g[field] for g in labels.values()), field          # an "always no" model cannot score 100%
