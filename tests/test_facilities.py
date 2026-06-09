# tests/test_facilities.py
import json
import sqlite3

from jforest.db import init_db, save_raw
from jforest.facilities import build_facility_text, extract_facilities, run_facility_extraction
from jforest.util import now_iso


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _seed_forest(conn, iid="0101"):
    conn.execute("INSERT INTO forests (instt_id, name, fetched_at) VALUES (?, '유명산', ?)", (iid, now_iso()))
    save_raw(conn, "u", "forest_intro", iid, 200,
             "<html><body>9갈래 계곡의 맑은 물에서 물놀이가 가능합니다.</body></html>", now_iso())
    save_raw(conn, "u", "forest_program", iid, 200,
             "<html><body>숲해설 프로그램 운영기간 3월~12월</body></html>", now_iso())
    # 바베큐는 기존 객실 이용안내에서
    conn.execute("INSERT INTO rooms (goods_id, instt_id, fetched_at) VALUES ('G1', ?, ?)", (iid, now_iso()))
    conn.execute("INSERT INTO room_usage_texts (goods_id, usage_guide, fetched_at) "
                 "VALUES ('G1', '연중 바베큐 이용이 불가능합니다.', ?)", (now_iso(),))
    conn.commit()


def test_build_facility_text_merges_sources():
    conn = _conn()
    _seed_forest(conn)
    text = build_facility_text(conn, "0101")
    assert "물놀이" in text
    assert "숲해설" in text
    assert "바베큐 이용이 불가능" in text  # 객실 안내에서 합쳐짐
    assert "<html>" not in text  # HTML 제거됨


def _fake_generator(prompt):
    # 프롬프트에 근거가 있으면 그대로 분류하는 가짜 LLM
    return json.dumps({
        "waterPlay": {"v": "O", "evidence": "계곡 물놀이 가능"},
        "barbecue": {"v": "X", "evidence": "연중 바베큐 불가능"},
        "forestGuide": {"v": "O", "evidence": "숲해설 프로그램"},
    })


def test_extract_facilities_normalizes_tristate():
    facts = extract_facilities("아무 텍스트", generator=_fake_generator)
    assert facts["water_play"] == "O"
    assert facts["barbecue"] == "X"
    assert facts["forest_guide"] == "O"
    assert facts["barbecue_evidence"] == "연중 바베큐 불가능"


def test_extract_facilities_unknown_maps_to_jeongbo_eopseum():
    gen = lambda p: json.dumps({"waterPlay": {"v": "unknown"}, "barbecue": {}, "forestGuide": {"v": ""}})
    facts = extract_facilities("x", generator=gen)
    assert facts["water_play"] == "정보없음"
    assert facts["barbecue"] == "정보없음"
    assert facts["forest_guide"] == "정보없음"


def test_run_facility_extraction_persists():
    conn = _conn()
    _seed_forest(conn)
    n = run_facility_extraction(conn, generator=_fake_generator, model="test", workers=1)
    assert n == 1
    row = conn.execute("SELECT * FROM forest_facilities WHERE instt_id='0101'").fetchone()
    assert row["water_play"] == "O"
    assert row["barbecue"] == "X"
    assert row["forest_guide"] == "O"
    assert row["needs_review"] == 0


def test_run_facility_extraction_flags_parse_error():
    conn = _conn()
    _seed_forest(conn)
    bad = lambda p: "not json at all"
    n = run_facility_extraction(conn, generator=bad, model="test", workers=1)
    assert n == 1
    row = conn.execute("SELECT needs_review, water_play FROM forest_facilities WHERE instt_id='0101'").fetchone()
    assert row["needs_review"] == 1
    assert row["water_play"] is None
