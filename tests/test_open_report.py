# tests/test_open_report.py
import sqlite3
from datetime import date

from jforest.db import init_db
from jforest.fcfs_report import (
    build_open_events,
    build_open_report,
    collect_uncertain,
    parse_open_event,
    _region,
)
from jforest.util import now_iso

# 2026-07-01 = 수, 07-02 = 목, 07-04 = 토, 07-15 = 수
WED = date(2026, 7, 1)
THU = date(2026, 7, 2)
SAT = date(2026, 7, 4)


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _forest(conn, iid, name, sido=1):
    conn.execute(
        "INSERT INTO forests (instt_id, name, sido_code, fetched_at) VALUES (?,?,?,?)",
        (iid, name, sido, now_iso()),
    )


def _policy(conn, iid, method, detail=""):
    conn.execute(
        "INSERT INTO reservation_policies (instt_id, fcfs_method, fcfs_detail, fetched_at) "
        "VALUES (?,?,?,?)",
        (iid, method, detail, now_iso()),
    )


def _detail(conn, iid, rule_id, text, title="정책"):
    conn.execute(
        "INSERT INTO reservation_policy_details (instt_id, rule_id, title, detail_text, fetched_at) "
        "VALUES (?,?,?,?,?)",
        (iid, rule_id, title, text, now_iso()),
    )


def _fac(conn, iid, wp, bbq, fg, needs_review=0):
    conn.execute(
        "INSERT INTO forest_facilities (instt_id, water_play, barbecue, forest_guide, "
        "needs_review, extracted_at) VALUES (?,?,?,?,?,?)",
        (iid, wp, bbq, fg, needs_review, now_iso()),
    )


# ── parse_open_event ─────────────────────────────────────────────

def test_parse_monthly_with_time():
    pe = parse_open_event("○ 예약 신청\n매월 4일 오전 9시~ 8일 오후 6시", "105")
    assert pe["kind"] == "monthly" and pe["key"] == 4
    assert pe["open_time"] == "오전 9시" and pe["conf"] == "확정"


def test_parse_weekly_with_hhmm():
    pe = parse_open_event("예약신청 : 매주 월요일 09:00~ 23:00", "105")
    assert pe["kind"] == "weekly" and pe["key"] == 0  # 월=0
    assert pe["open_time"] == "오전 9시"


def test_parse_bare_weekday():
    pe = parse_open_event("○ 예약 신청 화요일 오전 9시~ 목요일", "105")
    assert pe["kind"] == "weekly" and pe["key"] == 1  # 화=1


def test_parse_national_fallback_when_unparseable():
    # 주말추첨(102)은 날짜 못 뽑아도 국립 상수(매월 4일 오전9시)로 폴백
    pe = parse_open_event("접수 안내(상세 별도)", "102")
    assert pe["kind"] == "monthly" and pe["key"] == 4 and pe["conf"] == "추정"


def test_parse_returns_none_for_unparseable_local():
    # 지역주민(105)은 상수 폴백 없음 → None
    assert parse_open_event("자세한 일정은 공지 참조", "105") is None


def test_parse_section_boundary_ignores_later_date():
    # 앵커 뒤 첫 섹션만 본다: '당첨자 발표 매월 10일'을 오탐하지 않음
    text = "○ 예약신청\n매월 4일 오전 9시\n○ 당첨자 발표\n매월 10일"
    pe = parse_open_event(text, "105")
    assert pe["key"] == 4


# ── 분류 ────────────────────────────────────────────────────────

def test_region_mapping():
    assert _region(3) == "충북" and _region(1) == "경기·인천" and _region(99) == "기타"


def test_rule_104_is_local_not_lottery():
    conn = _conn()
    _forest(conn, "L1", "우대추첨휴양림")
    _detail(conn, "L1", "104", "○ 예약 신청\n매월 1일 오전 9시", "지역주민우대추첨제")
    conn.commit()
    events = build_open_events(conn, WED)  # 7/1 = 매월 1일
    assert [e["type_group"] for e in events] == ["지역주민"]


def test_rule_211_excluded():
    conn = _conn()
    _forest(conn, "D1", "다자녀휴양림")
    _detail(conn, "D1", "211", "○ 예약 신청\n매월 1일 오전 9시", "다자녀추첨제")
    conn.commit()
    assert build_open_events(conn, WED) == []


# ── build_open_events ───────────────────────────────────────────

def test_fcfs_opens_on_its_weekday():
    conn = _conn()
    _forest(conn, "0101", "수요일휴양림")
    _policy(conn, "0101", "6주 수요일", "매주 수요일 오전 9시부터")
    conn.commit()
    ev_wed = build_open_events(conn, WED)
    assert len(ev_wed) == 1 and ev_wed[0]["type_group"] == "선착순"
    assert ev_wed[0]["open_time"] == "오전 9시"
    assert build_open_events(conn, THU) == []


def test_weekend_lottery_opens_on_day_4():
    conn = _conn()
    _forest(conn, "0101", "주말추첨휴양림")
    _detail(conn, "0101", "102", "○ 신청 접수 기간\n매월 4일 오전 9시~", "주말추첨제")
    conn.commit()
    assert build_open_events(conn, SAT)[0]["type_group"] == "추첨"  # 7/4
    assert build_open_events(conn, WED) == []  # 7/1 아님


def test_general_open_on_15th_for_weekend_lottery_forests():
    conn = _conn()
    _forest(conn, "0101", "국립휴양림")
    _detail(conn, "0101", "102", "○ 신청 접수 기간\n매월 4일 오전 9시", "주말추첨제")
    conn.commit()
    events = build_open_events(conn, date(2026, 7, 15))
    labels = [e["type_label"] for e in events]
    assert any("일반오픈" in l for l in labels)


def test_merge_same_forest_group_time():
    # 같은 휴양림·그룹·시각 채널은 1행으로 병합, type_label 결합
    conn = _conn()
    _forest(conn, "0101", "병합휴양림")
    _detail(conn, "0101", "104", "○ 예약 신청\n매월 1일 오전 9시", "지역주민우대추첨제")
    _detail(conn, "0101", "105", "○ 예약 신청\n매월 1일 오전 9시", "지역주민우선예약")
    conn.commit()
    events = [e for e in build_open_events(conn, WED) if e["type_group"] == "지역주민"]
    assert len(events) == 1
    assert "·" in events[0]["type_label"]  # 우대추첨·우선 결합


def test_facility_marks_use_triangle_for_unknown():
    conn = _conn()
    _forest(conn, "0101", "시설휴양림")
    _policy(conn, "0101", "6주 수요일", "매주 수요일 오전 9시")
    _fac(conn, "0101", "O", "정보없음", "O")
    conn.commit()
    e = build_open_events(conn, WED)[0]
    assert e["water_play"] == "O" and e["barbecue"] == "△" and e["forest_guide"] == "O"


def test_needs_review_facility_is_triangle():
    conn = _conn()
    _forest(conn, "0101", "리뷰휴양림")
    _policy(conn, "0101", "6주 수요일", "매주 수요일 오전 9시")
    _fac(conn, "0101", "O", "X", "O", needs_review=1)
    conn.commit()
    e = build_open_events(conn, WED)[0]
    assert e["water_play"] == "△" and e["barbecue"] == "△"


# ── collect_uncertain / build_open_report ───────────────────────

def test_uncertain_excludes_parseable_and_fcfs():
    conn = _conn()
    _forest(conn, "0101", "명확휴양림")
    _policy(conn, "0101", "6주 수요일", "일정 미상 프로즈")  # 선착순은 uncertain에서 제외
    _detail(conn, "0101", "105", "직접 확인 요망", "지역주민우선예약")  # 파싱실패 → uncertain
    _forest(conn, "0102", "명확2")
    _detail(conn, "0102", "105", "○ 예약 신청\n매월 1일 오전 9시", "지역주민우선예약")  # 파싱성공
    conn.commit()
    unc = collect_uncertain(conn)
    assert [u["instt_id"] for u in unc] == ["0101"]
    assert unc[0]["type_group"] == "지역주민"


def test_build_open_report_shape():
    conn = _conn()
    _forest(conn, "0101", "수요일휴양림", sido=3)
    _policy(conn, "0101", "6주 수요일", "매주 수요일 오전 9시")
    conn.commit()
    rep = build_open_report(conn, WED)
    assert rep["date"] == "2026-07-01" and rep["weekday"] == "수"
    assert rep["total"] == 1
    assert rep["groups"][0]["type_group"] == "선착순"
    assert rep["groups"][0]["events"][0]["region"] == "충북"
    assert "성수기추첨" in rep["seasonal_note"]


def test_empty_day_returns_no_groups():
    conn = _conn()
    _forest(conn, "0101", "수요일휴양림")
    _policy(conn, "0101", "6주 수요일", "매주 수요일 오전 9시")
    conn.commit()
    rep = build_open_report(conn, THU)  # 목요일 → 아무것도 안 열림
    assert rep["total"] == 0 and rep["groups"] == []
