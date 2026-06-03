# tests/test_parser_discounts.py
from pathlib import Path
from jforest.parsers.discounts import parse_discounts
import json

FX = Path(__file__).parent / "fixtures"

def test_parse_discounts_first_row():
    rows = parse_discounts((FX / "discount.html").read_text(encoding="utf-8"))
    assert len(rows) >= 1
    r = rows[0]
    assert "장애인" in r["target"]
    assert r["category"] == "정율"
    assert r["timing"] == "결제시할인"
    assert r["apply_date"] == "2000-01-01"
    room = json.loads(r["room_rates"])
    assert room["off_weekday"] == "50%"
