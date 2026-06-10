# tests/test_fcfs_report.py
import sqlite3
from datetime import date

from jforest.db import init_db
from jforest.fcfs_report import build_fcfs_report, format_report
from jforest.util import now_iso


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _add(conn, instt_id, name, method, detail=""):
    conn.execute(
        "INSERT INTO forests (instt_id, name, fetched_at) VALUES (?, ?, ?)",
        (instt_id, name, now_iso()),
    )
    conn.execute(
        "INSERT INTO reservation_policies (instt_id, fcfs_method, fcfs_detail, fetched_at) "
        "VALUES (?, ?, ?, ?)",
        (instt_id, method, detail, now_iso()),
    )
    conn.commit()


# 2026-06-10 = 수요일, 2026-06-09 = 화요일, 2026-07-01 = 수요일(매월 1일)
WED = date(2026, 6, 10)
TUE = date(2026, 6, 9)


def test_weekly_group_opens_only_on_its_weekday():
    conn = _conn()
    _add(conn, "0101", "강씨봉자연휴양림", "6주 수요일")
    rows_wed = build_fcfs_report(conn, WED)
    assert [r["name"] for r in rows_wed] == ["강씨봉자연휴양림"]
    assert rows_wed[0]["week_label"] == "6주차"
    # 화요일엔 수요일 그룹이 열리지 않는다
    assert build_fcfs_report(conn, TUE) == []


def test_monthly_group_opens_on_first_of_month_only():
    conn = _conn()
    _add(conn, "0181", "달천예당힐링자연휴양림", "익월말")
    assert build_fcfs_report(conn, date(2026, 7, 1))  # 매월 1일 오픈
    assert build_fcfs_report(conn, date(2026, 7, 2)) == []


def test_weekly_and_monthly_do_not_leak_into_each_other():
    conn = _conn()
    _add(conn, "0101", "수요일휴양림", "6주 수요일")
    _add(conn, "0181", "월초휴양림", "익월말")
    names_wed = {r["name"] for r in build_fcfs_report(conn, WED)}
    assert names_wed == {"수요일휴양림"}  # 수요일이지만 1일이 아니므로 월초그룹 제외


def test_monthly_group_uses_actual_open_day_from_detail():
    # '익월말' method도 본문의 '매월 N일'을 파싱해 그 날에만 열려야 한다(칼봉산=10일).
    conn = _conn()
    detail = "예약 신청은 매월 10일 전체 휴양림 객실 오후 4시부터, 다음달 말일까지 가능합니다."
    _add(conn, "0182", "칼봉산자연휴양림", "익월말", detail)
    assert [r["name"] for r in build_fcfs_report(conn, date(2026, 6, 10))] == ["칼봉산자연휴양림"]
    assert build_fcfs_report(conn, date(2026, 6, 1)) == []  # 1일엔 안 열림


def test_monthly_group_without_day_in_detail_defaults_to_first():
    conn = _conn()
    _add(conn, "0181", "기본월간휴양림", "익월말", "매월 오픈 안내(일자 미상)")
    assert build_fcfs_report(conn, date(2026, 7, 1))
    assert build_fcfs_report(conn, date(2026, 7, 10)) == []


def test_detail_policy_parsed_from_fcfs_detail():
    conn = _conn()
    detail = "예약 신청은 매주 수요일 ... 오전 9시부터, 6주차 월요일까지 가능합니다."
    _add(conn, "0205", "상세정책휴양림", "상세정책", detail)
    rows = build_fcfs_report(conn, WED)
    assert [r["name"] for r in rows] == ["상세정책휴양림"]
    assert rows[0]["week_label"] == "6주차"


def test_detail_monthly_on_specific_day():
    conn = _conn()
    detail = "예약 신청은 매월 5일 전체 휴양림 객실 모두 오전 9시부터, 다음 달 말일까지 가능합니다."
    _add(conn, "0257", "매월5일휴양림", "상세정책", detail)
    assert build_fcfs_report(conn, date(2026, 7, 5))  # 5일 오픈
    assert build_fcfs_report(conn, date(2026, 7, 1)) == []  # 1일엔 안 열림


def test_format_report_matches_expected_shape():
    conn = _conn()
    _add(conn, "0101", "강씨봉자연휴양림", "6주 수요일")
    text = format_report(build_fcfs_report(conn, WED), WED)
    assert "2026년 6월 10일 (수요일)" in text
    assert "선착순 예약 시작 휴양림 리스트" in text
    assert "1. 강씨봉자연휴양림" in text
    # 주간은 마지막 예약가능일(오픈일+6주-1=7/21 화)을 구체 표기
    assert "6주차(~7/21 화) 예약가능" in text


def test_report_includes_facility_flags_when_available():
    conn = _conn()
    _add(conn, "0101", "강씨봉자연휴양림", "6주 수요일")
    conn.execute(
        "INSERT INTO forest_facilities (instt_id, water_play, barbecue, forest_guide, extracted_at) "
        "VALUES ('0101','O','X','O',?)",
        (now_iso(),),
    )
    conn.commit()
    rows = build_fcfs_report(conn, WED)
    assert rows[0]["water_play"] == "O" and rows[0]["barbecue"] == "X"
    text = format_report(rows, WED)
    assert "물놀이(O), 바베큐(X), 숲해설(O), 6주차(~7/21 화) 예약가능" in text


def test_format_report_separates_monthly_highlight_from_weekly():
    conn = _conn()
    _add(conn, "0101", "수요일주간휴양림", "6주 수요일")
    _add(conn, "0182", "칼봉산자연휴양림", "익월말",
         "예약 신청은 매월 10일 객실 오후 4시부터, 다음달 말일까지 가능합니다.")
    text = format_report(build_fcfs_report(conn, WED), WED)
    # 월간 강조 섹션이 주간 섹션보다 앞에 온다
    monthly_pos = text.index("오늘 지정 오픈 (월간)")
    weekly_pos = text.index("매주 수요일 반복 오픈 (주간)")
    assert monthly_pos < weekly_pos
    assert "★ 오늘 지정 오픈 (월간) — 1곳" in text
    assert "칼봉산자연휴양림" in text[monthly_pos:weekly_pos]  # 월간 섹션에 위치
    assert "수요일주간휴양림" in text[weekly_pos:]  # 주간 섹션에 위치


def test_format_report_no_monthly_today_shows_empty_highlight():
    conn = _conn()
    _add(conn, "0101", "수요일주간휴양림", "6주 수요일")
    text = format_report(build_fcfs_report(conn, WED), WED)
    assert "오늘이 지정 오픈일인 월간 휴양림 없음" in text
    assert "매주 수요일 반복 오픈 (주간) — 1곳" in text


def test_format_report_empty_day():
    conn = _conn()
    _add(conn, "0101", "강씨봉자연휴양림", "6주 수요일")
    text = format_report(build_fcfs_report(conn, TUE), TUE)
    assert "2026년 6월 9일 (화요일)" in text
    assert "오늘 선착순 예약이 시작되는 휴양림이 없습니다" in text
