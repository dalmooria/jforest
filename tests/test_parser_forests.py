# tests/test_parser_forests.py
from pathlib import Path
from jforest.parsers.forests import parse_forest_list_json, parse_forest_list_html

FX = Path(__file__).parent / "fixtures"

def test_parse_json_returns_id_name_arcd_typecode():
    rows = parse_forest_list_json((FX / "forest_list_sido1.json").read_text(encoding="utf-8"))
    assert len(rows) >= 20
    sample = rows[0]
    assert set(sample) == {"instt_id", "name", "arcd", "instt_type_code", "instt_type"}
    assert all(r["instt_id"] for r in rows)

def test_parse_json_derives_instt_type_label_from_code():
    rows = parse_forest_list_json((FX / "forest_list_sido1.json").read_text(encoding="utf-8"))
    seen = {r["instt_type_code"]: r["instt_type"] for r in rows}
    label = {"01": "국립", "02": "공립", "04": "사립"}
    for code, lab in seen.items():
        assert lab == label.get(code)

def test_parse_json_contains_known_forest():
    rows = parse_forest_list_json((FX / "forest_list_sido1.json").read_text(encoding="utf-8"))
    ids = {r["instt_id"] for r in rows}
    assert "ID02030019" in ids  # 강씨봉

def test_parse_html_extracts_items_from_js_positions():
    items = parse_forest_list_html((FX / "forest_list_html_p1.html").read_text(encoding="utf-8"))
    # 페이지당 4곳
    assert len(items) == 4
    by_id = {it["instt_id"]: it for it in items}
    assert "ID02030002" in by_id  # 가리산
    it = by_id["ID02030002"]
    assert "가리산" in (it["name"] or "")
    assert it["homepage_url"] == "https://garisan.foresttrip.go.kr"
    # 미보강 필드는 None
    assert it["instt_type"] is None and it["summary"] is None

def test_parse_html_handles_numeric_id():
    items = parse_forest_list_html((FX / "forest_list_html_p1.html").read_text(encoding="utf-8"))
    assert "0113" in {it["instt_id"] for it in items}  # 가리왕산(숫자형 id)
