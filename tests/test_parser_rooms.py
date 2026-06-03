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


def test_parse_room_list_handles_national_forest_goods_id():
    # 국립휴양림(숫자형 instt_id)의 goods_id는 GID가 아니라 G0…(예: G01010100101001008900338) 형식.
    rooms = parse_room_list((FX / "room_list_national.html").read_text(encoding="utf-8"))
    assert len(rooms) >= 1
    by_id = {r["goods_id"]: r for r in rooms}
    r = by_id["G01010100101001008900338"]
    assert r["room_type"] == "숲속의집"
    assert r["name"] == "고라니"
    assert r["capacity_max"] == 5
    assert "31" in r["area"]
    # GID로 시작하지 않는 국립 형식도 수집된다
    assert all(r["goods_id"].startswith("G") for r in rooms)
    assert any(not r["goods_id"].startswith("GID") for r in rooms)
