import json
import re
from pathlib import Path

from src.pipeline import load_golden, load_texts
from src.schema import TicketExtraction, json_schema

DATA = Path(__file__).resolve().parent.parent / "data"


def test_schema_meets_assignment_requirements():
    s = json_schema()
    props = s["properties"]
    assert len(props) >= 6
    assert any("enum" in p for p in props.values())                    # has an enum
    assert props["product"]["type"] == "object"                        # has a nested object
    assert "$ref" not in json.dumps(s)                                 # schema is self-contained


def test_golden_labels_match_schema():
    for gid, g in load_golden(DATA / "golden").items():
        label = TicketExtraction.model_validate(g)                     # full schema, nothing filled in
        oid = label.product.order_id
        assert oid is None or re.fullmatch(r"ES-\d{5}", oid), gid


def test_dataset_size():
    texts = load_texts(DATA / "texts")
    golden = load_golden(DATA / "golden")
    ids = {t["id"] for t in texts}
    assert len(texts) >= 30 and all(t["text"].strip() for t in texts)
    assert len(golden) >= 10 and set(golden) <= ids                    # every label has its text
