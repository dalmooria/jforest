# tests/test_alerts.py
import sqlite3
from datetime import date

from jforest.alerts import classify, parse_period, extract_blocks
from jforest.db import init_db
from jforest.fcfs_report import build_open_report, active_restrictions
from jforest.util import now_iso


def test_classify_by_keyword():
    assert classify("국립변산 숲속의집 유지보수공사 안내") == "공사"
    assert classify("예약제외 시설물 지정·운영(26년 7월)") == "예약제외"
    assert classify("정비공사에 따른 임시 휴관 알림") == "휴관"  # 휴관 우선
    assert classify("객실 판매 제한 안내") == "예약제외"  # '판매 제한'=예약제외 성격
    assert classify("시설 안전 점검 안내") == "점검"
    assert classify("정원박람회 행사에 따른 예약제외") in ("예약제외", "행사")
    assert classify("일반 공지사항") is None


def test_parse_period_range():
    s, e, k = parse_period("유지보수공사(2026.6.3.~7.14.)")
    assert s == "2026-06-03" and e == "2026-07-14" and k == "range"


def test_parse_period_range_with_spaces_and_year2():
    s, e, k = parse_period("행사(2026. 6. 11 . ~ 6. 29.)")
    assert s == "2026-06-11" and e == "2026-06-29"


def test_parse_period_month():
    s, e, k = parse_period("예약제외 시설물(26년 7월)")
    assert s == "2026-07-01" and e == "2026-07-31" and k == "month"


def test_parse_period_asof_is_month_end():
    s, e, k = parse_period("예약 제외 시설물 현황(2026.6.1. 기준)")
    assert s == "2026-06-01" and e == "2026-06-30" and k == "asof"


def test_parse_period_none():
    assert parse_period("기간 정보 없는 공지") is None


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _notice(conn, iid, twbbs, title, body=""):
    conn.execute(
        "INSERT INTO notices (instt_id, twbbs_id, title, updated_at, body_text, fetched_at) "
        "VALUES (?,?,?,?,?,?)",
        (iid, twbbs, title, "2026-06-01", body, now_iso()),
    )


def test_extract_blocks_dates_from_title_and_body():
    conn = _conn()
    conn.execute("INSERT INTO forests (instt_id,name,fetched_at) VALUES ('0101','옥전',?)", (now_iso(),))
    _notice(conn, "0101", "t1", "옥전 시설 공사안내(2026.7.1.~7.31.)")
    _notice(conn, "0101", "t2", "옥전 보수공사 안내", body="공사기간: 2026.8.1.~2026.8.20. 예약불가")
    _notice(conn, "0101", "t3", "일반 안내문")  # 비관련 → 제외
    conn.commit()
    n = extract_blocks(conn, since="2025-01-01")
    assert n == 2  # 관련 2건만
    dated = conn.execute("SELECT COUNT(*) FROM reservation_blocks WHERE start_date IS NOT NULL").fetchone()[0]
    assert dated == 2  # 제목/본문 각각에서 기간 파싱


def test_report_includes_active_restrictions_and_event_alert():
    conn = _conn()
    conn.execute("INSERT INTO forests (instt_id,name,sido_code,fetched_at) VALUES ('0101','옥전',3,?)", (now_iso(),))
    conn.execute("INSERT INTO reservation_policies (instt_id,fcfs_method,fcfs_detail,fetched_at) VALUES ('0101','6주 수요일','매주 수요일 오전 9시',?)", (now_iso(),))
    _notice(conn, "0101", "t1", "옥전 공사 안내(2026.7.1.~7.31.)")
    conn.commit()
    extract_blocks(conn, since="2025-01-01")
    on = date(2026, 7, 1)  # 수요일 + 공사기간 내
    restr = active_restrictions(conn, on)
    assert len(restr) == 1 and restr[0]["alert_type"] == "공사"
    rep = build_open_report(conn, on)
    assert len(rep["restrictions"]) == 1
    ev = rep["groups"][0]["events"][0]  # 선착순 옥전
    assert ev["alerts"] and ev["alerts"][0]["alert_type"] == "공사"


def test_expired_block_not_active():
    conn = _conn()
    conn.execute("INSERT INTO forests (instt_id,name,fetched_at) VALUES ('0101','옥전',?)", (now_iso(),))
    _notice(conn, "0101", "t1", "옥전 공사(2026.5.1.~5.31.)")
    conn.commit()
    extract_blocks(conn, since="2025-01-01")
    assert active_restrictions(conn, date(2026, 7, 1)) == []  # 만료


def test_body_period_rejects_past_reference():
    from jforest.alerts import _body_period
    # 공지일(2026-06) 이전에 끝나는 과거 날짜는 배제(요금개정 등 오참조 방지)
    assert _body_period("2021.5.1.~5.31. 요금 인상 이력", "2026-06-01") is None
    # 공지일 이후/현재 기간은 유지
    p = _body_period("공사기간 2026.7.1.~7.31. 예약불가", "2026-06-01")
    assert p and p[0] == "2026-07-01"


def test_body_period_anchor_precision():
    from jforest.alerts import _body_period
    # '기간' 앵커 근처 기간을 우선 취함
    p = _body_period("휴관 기간: 2026.7.1.~7.10. 자세한 내용은 ...", "2026-06-01")
    assert p and p[0] == "2026-07-01" and p[1] == "2026-07-10"
