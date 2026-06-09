# tests/test_structure.py
import sqlite3
from jforest.db import init_db
from jforest.structure import select_high_value_notices, extract_facts, run_fact_extraction
from jforest.util import now_iso


def _notice(conn, iid, twbbs, content, title=""):
    conn.execute(
        "INSERT INTO notices (instt_id, twbbs_id, title, content_text, fetched_at) VALUES (?,?,?,?,?)",
        (iid, twbbs, title, content, now_iso()),
    )


def _att(conn, iid, twbbs, text):
    conn.execute(
        "INSERT INTO notice_attachments (instt_id, twbbs_id, file_master_id, file_id, extracted_text, downloaded, fetched_at) "
        "VALUES (?,?,?,?,?,1,?)",
        (iid, twbbs, f"FM{iid}{twbbs}", f"{iid}{twbbs}", text, now_iso()),
    )


def test_select_high_value_notices_matches_operational_keywords():
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    _notice(conn, "I", "A", "객실 사용료 인상 안내 2026.6.1.부터")
    _notice(conn, "I", "B", "안녕하세요 방문객 여러분께 인사드립니다")
    conn.commit()
    keys = {(r["instt_id"], r["twbbs_id"]) for r in select_high_value_notices(conn)}
    assert ("I", "A") in keys
    assert ("I", "B") not in keys


def test_select_high_value_notices_includes_attachment_text():
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    _notice(conn, "I", "A", "첨부파일 참조")          # 본문엔 키워드 없음
    _att(conn, "I", "A", "예약제외 시설물 리스트: 101호, 102호")  # 첨부에 키워드
    conn.commit()
    keys = {(r["instt_id"], r["twbbs_id"]) for r in select_high_value_notices(conn)}
    assert ("I", "A") in keys


def test_select_high_value_notices_skips_already_structured():
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    _notice(conn, "I", "A", "객실 요금 변경 안내")
    conn.execute("INSERT INTO notice_facts (instt_id, twbbs_id, facts_json, extracted_at) VALUES ('I','A','{}',?)", (now_iso(),))
    conn.commit()
    keys = {(r["instt_id"], r["twbbs_id"]) for r in select_high_value_notices(conn)}
    assert ("I", "A") not in keys  # 이미 처리됨 → 재처리 안 함


def test_build_notice_text_caps_huge_input():
    # 초대형 첨부(전국 예약제외 목록 등)는 잘라 LLM 출력 토큰 초과를 막는다.
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    from jforest.structure import build_notice_text
    _notice(conn, "I", "A", "짧은 본문")
    _att(conn, "I", "A", "가" * 100000)
    conn.commit()
    text = build_notice_text(conn, "I", "A", max_chars=15000)
    assert len(text) <= 15000


def test_extract_facts_parses_generator_json():
    facts = extract_facts(
        "객실 사용료 인상",
        generator=lambda prompt: '{"roomPrices":[{"label":"성수기","price":50000}],"needs_review":false}',
    )
    assert facts["roomPrices"][0]["price"] == 50000


def test_extract_facts_strips_markdown_fences():
    facts = extract_facts(
        "x",
        generator=lambda prompt: '```json\n{"barbecue":"금지","needs_review":false}\n```',
    )
    assert facts["barbecue"] == "금지"


def test_run_fact_extraction_stores_facts():
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    _notice(conn, "I", "A", "퇴실시간 11시로 조정 안내")
    conn.commit()
    n = run_fact_extraction(conn, generator=lambda p: '{"reservationNotes":["퇴실 11시"],"needs_review":false}')
    assert n == 1
    row = conn.execute("SELECT facts_json, needs_review FROM notice_facts WHERE instt_id='I' AND twbbs_id='A'").fetchone()
    assert "퇴실" in row["facts_json"]
    assert row["needs_review"] == 0


def test_run_fact_extraction_concurrent_stores_all():
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    for i in range(25):
        _notice(conn, "I", f"N{i}", "객실 요금 변경 안내")
    conn.commit()
    n = run_fact_extraction(
        conn, generator=lambda p: '{"reservationNotes":["x"],"needs_review":false}', workers=8,
    )
    assert n == 25
    assert conn.execute("SELECT COUNT(*) FROM notice_facts").fetchone()[0] == 25


def test_run_fact_extraction_flags_needs_review_on_parse_error():
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    _notice(conn, "I", "A", "객실 요금 인상")
    conn.commit()
    n = run_fact_extraction(conn, generator=lambda p: "이건 JSON이 아님")
    assert n == 1
    row = conn.execute("SELECT needs_review FROM notice_facts WHERE instt_id='I' AND twbbs_id='A'").fetchone()
    assert row["needs_review"] == 1
