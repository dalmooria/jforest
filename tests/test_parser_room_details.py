# tests/test_parser_room_details.py
from pathlib import Path
from jforest.parsers.room_details import parse_room_detail

FX = Path(__file__).parent / "fixtures"

def test_parse_room_detail_capacity_and_area():
    d = parse_room_detail((FX / "room_detail.html").read_text(encoding="utf-8"))
    assert d["capacity_standard"] == 2
    assert d["capacity_max"] == 3
    assert "20" in d["area"]

def test_parse_room_detail_prices():
    d = parse_room_detail((FX / "room_detail.html").read_text(encoding="utf-8"))
    prices = {(p["season"], p["day_type"]): p["price"] for p in d["prices"]}
    assert prices[("off", "weekday")] == 60000
    assert prices[("off", "weekend")] == 80000
    assert prices[("peak", "weekday")] == 80000
    assert prices[("peak", "weekend")] == 80000

def test_parse_room_detail_texts():
    d = parse_room_detail((FX / "room_detail.html").read_text(encoding="utf-8"))
    assert "전자레인지" in (d["amenities"] or "")
    assert d["usage_guide"] and len(d["usage_guide"]) > 20
