# jforest/alerts.py
"""공지사항에서 '예약불가/공사/예약제외' 기간을 규칙 기반으로 추출한다.

notices.instt_id가 이미 휴양림을 가리키므로 대상은 조인으로 확정된다.
제목/본문에서 alert_type(사유)과 적용 기간을 정규식으로 뽑아 reservation_blocks에
적재한다. 날짜를 못 뽑으면 needs_review=1로 남기고 날짜매칭 대상에서 제외한다.

LLM은 쓰지 않는다(결정적·비용 0). 저신뢰(needs_review) 건은 향후 LLM 보강 여지.
"""
import re
from calendar import monthrange
from datetime import date

from jforest.util import now_iso

# 제목 키워드 → alert_type. 우선순위 순(앞이 우선).
_TYPE_RULES = [
    ("휴관", ["휴관", "휴장", "임시 휴", "임시휴"]),
    ("공사", ["공사", "보수", "리모델링", "정비", "개선사업", "보완사업"]),
    ("예약제외", ["예약제외", "예약 제외", "제외 시설", "제외시설", "판매 제한", "판매제한"]),
    ("점검", ["점검"]),
    ("재해", ["재해", "태풍", "산사태", "폭우", "폭설", "동파"]),
    ("행사", ["행사", "축제", "박람회", "대회"]),
]
_RELEVANT = [kw for _, kws in _TYPE_RULES for kw in kws] + ["이용 제한", "이용제한", "예약불가", "예약 불가"]

# 날짜 범위: 2026.6.3.~7.14. / 2026. 6. 11 . ~ 6. 29. / 2026.05.27.~28
_RE_RANGE = re.compile(
    r"(20\d{2})\s*[.\-]\s*(\d{1,2})\s*[.\-]\s*(\d{1,2})\s*\.?\s*~\s*"
    r"(?:(20\d{2})\s*[.\-]\s*)?(\d{1,2})\s*[.\-]\s*(\d{1,2})"
)
# 월 단위: (26년 7월) / (2026년 7월)
_RE_MONTH = re.compile(r"(\d{2,4})\s*년\s*(\d{1,2})\s*월")
# 기준일: 2026.6.1. 기준
_RE_ASOF = re.compile(r"(20\d{2})\s*[.\-]\s*(\d{1,2})\s*[.\-]\s*(\d{1,2})\s*\.?\s*기준")


def classify(title: str):
    t = title or ""
    for atype, kws in _TYPE_RULES:
        if any(k in t for k in kws):
            return atype
    if any(k in t for k in ("이용 제한", "이용제한", "예약불가", "예약 불가")):
        return "공사"  # 사유 불명확한 이용제한은 공사로 총칭
    return None


def _yr(y: int) -> int:
    return y + 2000 if y < 100 else y


def parse_period(text: str):
    """(start_date, end_date, kind) 또는 None. kind: range|month|asof."""
    t = text or ""
    m = _RE_RANGE.search(t)
    if m:
        y1, m1, d1, y2, m2, d2 = m.groups()
        y1 = _yr(int(y1))
        y2 = _yr(int(y2)) if y2 else y1
        try:
            s = date(y1, int(m1), int(d1))
            e = date(y2, int(m2), int(d2))
            if e >= s:
                return s.isoformat(), e.isoformat(), "range"
        except ValueError:
            pass
    m = _RE_ASOF.search(t)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            s = date(y, mo, d)
            # '기준' 현황은 해당 월 말까지 유효로 본다(월간 갱신).
            e = date(y, mo, monthrange(y, mo)[1])
            return s.isoformat(), e.isoformat(), "asof"
        except ValueError:
            pass
    m = _RE_MONTH.search(t)
    if m:
        y, mo = _yr(int(m.group(1))), int(m.group(2))
        try:
            s = date(y, mo, 1)
            e = date(y, mo, monthrange(y, mo)[1])
            return s.isoformat(), e.isoformat(), "month"
        except ValueError:
            pass
    return None


# 본문에서 기간을 찾을 때, 관련 없는 날짜(요금개정일 등) 오참조를 줄이기 위해
# 기간을 암시하는 앵커 근처만 탐색한다.
_BODY_PERIOD_ANCHORS = ["기간", "까지", "공사", "휴관", "폐쇄", "운영 중단", "운영중단",
                        "운영 중지", "제한", "일정", "예약 불가", "예약불가", "이용 불가"]


def _body_period(body: str, notice_date: str = None):
    """본문에서 기간 파싱.

    1) '기간 암시 앵커'(공사기간·휴관 등) 근처를 우선 탐색(정밀).
    2) 없으면 본문의 첫 기간을 쓰되, 공지일(notice_date)보다 먼저 끝나는 기간은
       과거 참조(요금개정일 등)로 보고 배제한다(오참조 방지 + recall 유지).
    """
    t = (body or "")[:1000]
    for a in _BODY_PERIOD_ANCHORS:
        i = t.find(a)
        if i != -1:
            p = parse_period(t[max(0, i - 12): i + 60])
            if p:
                return p
    p = parse_period(t)
    if p and (not notice_date or p[1] >= notice_date[:10]):
        return p
    return None


def extract_blocks(conn, since: str = "2025-01-01") -> int:
    """관련 공지에서 블록을 추출해 reservation_blocks에 적재한다. 적재 건수 반환.

    DELETE+INSERT를 단일 트랜잭션(`with conn`)으로 묶어, 중간 실패 시 기존 데이터가
    비워진 채 남지 않도록 한다(성공 시 커밋, 예외 시 롤백).
    """
    like = " OR ".join("title LIKE ?" for _ in _RELEVANT)
    params = [f"%{k}%" for k in _RELEVANT]
    rows = conn.execute(
        f"SELECT instt_id, twbbs_id, title, updated_at, body_text, content_text FROM notices "
        f"WHERE ({like}) AND (updated_at >= ? OR updated_at IS NULL)",
        params + [since],
    ).fetchall()
    n = 0
    ts = now_iso()
    with conn:  # 원자적: 성공 시 커밋, 예외 시 롤백
        conn.execute("DELETE FROM reservation_blocks")
        for r in rows:
            atype = classify(r["title"])
            if not atype:
                continue
            # 기간은 제목 우선, 없으면 본문의 '기간 암시 앵커' 근처만 탐색(오참조 방지).
            period = parse_period(r["title"])
            if not period:
                body = ((r["body_text"] or "") + " " + (r["content_text"] or ""))[:1000]
                period = _body_period(body, r["updated_at"])
            # 기간을 못 뽑으면 needs_review(날짜매칭 제외)
            start = end = None
            needs_review = 1
            if period:
                start, end, _kind = period
                needs_review = 0
            conn.execute(
                "INSERT INTO reservation_blocks "
                "(instt_id, alert_type, scope, affected_units, start_date, end_date, "
                "reason, source_twbbs_id, needs_review, extracted_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (r["instt_id"], atype, None, None, start, end,
                 re.sub(r"\s+", " ", (r["title"] or "")).strip(),
                 r["twbbs_id"], needs_review, ts),
            )
            n += 1
    return n
