# tests/test_parser_rooms.py
from pathlib import Path
from jforest.parsers.rooms import parse_room_list

FX = Path(__file__).parent / "fixtures"

def test_parse_room_list_extracts_known_room():
    rooms = parse_room_list((FX / "room_list.html").read_text(encoding="utf-8"))
    by_id = {r["goods_id"]: r for r in rooms}
    r = by_id["GID020301240100101001001000004"]
    assert r["room_type"] == "숲속의집"
    assert r["name"] == "A동-101호(거류산)"
    assert r["capacity_max"] == 3
    assert "20" in r["area"]

def test_parse_room_list_all_have_goods_id():
    rooms = parse_room_list((FX / "room_list.html").read_text(encoding="utf-8"))
    assert len(rooms) >= 1
    assert all(r["goods_id"].startswith("GID") for r in rooms)
