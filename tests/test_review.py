# tests/test_review.py
import json
import sqlite3
from jforest.db import init_db
from jforest.review import validate_facts, run_revalidation, export_review_queue
from jforest.util import now_iso


def test_validate_facts_ok_when_has_content():
    review, issues = validate_facts({"reservationNotes": ["체크아웃 11시"], "needs_review": True})
    assert review is False
    assert issues == []


def test_validate_facts_allows_empty_as_non_operational():
    # 빈 결과는 비-운영 공지(미세먼지·축제 등 키워드 우연 매칭)가 대부분이라 검수 대상이 아니다.
    review, issues = validate_facts({"roomPrices": [], "discountPolicy": [], "waterPlay": None,
                                     "barbecue": None, "reservationNotes": [], "needs_review": False})
    assert review is False


def test_validate_facts_flags_missing_or_nonnumeric_price():
    review, issues = validate_facts({"roomPrices": [{"label": "성수기", "price": None}], "needs_review": False})
    assert review is True
    assert any("price" in i.lower() or "가격" in i for i in issues)


def test_validate_facts_accepts_plausible_price():
    review, issues = validate_facts({"roomPrices": [{"label": "성수기", "price": 65000}], "needs_review": False})
    assert review is False


def test_validate_facts_accepts_zero_price_as_free():
    # 0원 = 무료(어린이 물놀이시설 등)는 정상 정보 → 오탐 방지
    review, issues = validate_facts({"roomPrices": [{"label": "어린이물놀이", "price": 0}], "needs_review": False})
    assert review is False


def test_validate_facts_accepts_large_package_price():
    # 동계장박 4~5개월 등 장기 패키지는 수백만 원이 정상 → 오탐 방지
    review, issues = validate_facts({"roomPrices": [{"label": "하우스캠핑 5개월", "price": 2750000}], "needs_review": False})
    assert review is False


def test_validate_facts_accepts_low_admission_fee():
    # 입장료/주차료는 수백 원이 정상(어른 1000, 청소년 600, 주차 800 등) → 오탐 방지
    review, issues = validate_facts({"roomPrices": [{"label": "주차료", "price": 800}], "needs_review": False})
    assert review is False


def test_validate_facts_flags_parse_error():
    review, issues = validate_facts({"_parse_error": "Unterminated string"})
    assert review is True


def _fact(conn, iid, tw, facts):
    conn.execute(
        "INSERT INTO notice_facts (instt_id, twbbs_id, facts_json, needs_review, extracted_at) VALUES (?,?,?,?,?)",
        (iid, tw, json.dumps(facts, ensure_ascii=False), 1, now_iso()),
    )


def test_run_revalidation_clears_noise_keeps_real_issues():
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    _fact(conn, "I", "good", {"reservationNotes": ["체크아웃 11시"], "needs_review": True})   # 노이즈 → 해제
    _fact(conn, "I", "bad", {"roomPrices": [{"label": "x", "price": None}], "needs_review": False})  # 진짜 문제 → 유지
    conn.commit()
    run_revalidation(conn)
    good = conn.execute("SELECT needs_review FROM notice_facts WHERE twbbs_id='good'").fetchone()
    bad = conn.execute("SELECT needs_review FROM notice_facts WHERE twbbs_id='bad'").fetchone()
    assert good["needs_review"] == 0
    assert bad["needs_review"] == 1


def test_export_review_queue_writes_flagged_only(tmp_path):
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    conn.execute("INSERT INTO notices (instt_id, twbbs_id, title, content_text, fetched_at) VALUES ('I','bad','문제공지','원문내용',?)", (now_iso(),))
    _fact(conn, "I", "bad", {"roomPrices": [{"label": "x", "price": None}], "needs_review": False})
    _fact(conn, "I", "good", {"reservationNotes": ["ok"], "needs_review": False})
    conn.execute("UPDATE notice_facts SET needs_review=1 WHERE twbbs_id='bad'")
    conn.execute("UPDATE notice_facts SET needs_review=0 WHERE twbbs_id='good'")
    conn.commit()
    out = tmp_path / "queue.jsonl"
    n = export_review_queue(conn, str(out))
    assert n == 1
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["twbbs_id"] == "bad"
    assert "issues" in rec and rec["issues"]
    assert "title" in rec
