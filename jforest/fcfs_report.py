# jforest/fcfs_report.py
"""선착순(FCFS) 예약이 '해당일'에 열리는 휴양림을 리포팅한다.

데이터 출처: reservation_policies.fcfs_method / fcfs_detail (크롤 완료).
  - "N주 <요일>"  : 매주 그 요일 오픈 → N주차 예약가능 (예: "6주 수요일")
  - "익월말"       : 매월 1일 오픈 → 다음달 말일까지 예약가능
  - "상세정책"     : fcfs_method가 규칙을 담지 못해 fcfs_detail 본문에서 파싱

물놀이/바베큐 시설 정보는 현재 데이터에 휴양림 단위로 없어 보류한다
(소스의 선착순 예약 페이지 bbqYn/otsdWeterYn 필터는 로그인 세션 필요).
"""
import re
from datetime import date

WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]
_WD_INDEX = {name: i for i, name in enumerate(WEEKDAYS)}

# "6주 수요일", "6주 수" 모두 허용
_WEEKLY_METHOD = re.compile(r"(\d+)\s*주\s*([월화수목금토일])")
# 상세정책 본문: "매주 수요일 ... 6주차"
_DETAIL_WEEKDAY = re.compile(r"매주\s*([월화수목금토일])요일")
_DETAIL_WEEKNUM = re.compile(r"(\d+)\s*주차")
_DETAIL_MONTHLY = re.compile(r"매월\s*(\d+)\s*일")


def _classify(method: str, detail: str):
    """(kind, key, week_label) 또는 None을 돌려준다.

    kind: "weekly" | "monthly"
    key : weekly면 요일 인덱스(0=월), monthly면 오픈 일(day-of-month)
    week_label: 사람이 읽는 예약가능 시점 문구
    """
    method = (method or "").strip()
    detail = detail or ""

    m = _WEEKLY_METHOD.search(method)
    if m:
        return "weekly", _WD_INDEX[m.group(2)], f"{m.group(1)}주차"

    if method == "익월말":
        # "매월 1일 오픈 → 다음달 말일까지" (크롤된 본문 기준)
        return "monthly", 1, "익월 말일까지"

    if method == "상세정책":
        wd = _DETAIL_WEEKDAY.search(detail)
        if wd:
            num = _DETAIL_WEEKNUM.search(detail)
            label = f"{num.group(1)}주차" if num else "상세정책 확인"
            return "weekly", _WD_INDEX[wd.group(1)], label
        mon = _DETAIL_MONTHLY.search(detail)
        if mon:
            return "monthly", int(mon.group(1)), "익월 말일까지"

    return None


def _opens_on(kind, key, on_date: date) -> bool:
    if kind == "weekly":
        return on_date.weekday() == key
    if kind == "monthly":
        return on_date.day == key
    return False


def _has_facilities(conn) -> bool:
    return bool(
        conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='forest_facilities'"
        ).fetchone()
    )


def build_fcfs_report(conn, on_date: date) -> list:
    """on_date에 선착순 예약 창이 열리는 휴양림 목록(이름순)을 반환한다.

    forest_facilities 테이블이 있으면 물놀이/바베큐/숲해설 플래그를 함께 채운다.
    """
    if _has_facilities(conn):
        sql = (
            "SELECT f.instt_id, f.name, p.fcfs_method, p.fcfs_detail, "
            "ff.water_play, ff.barbecue, ff.forest_guide "
            "FROM forests f JOIN reservation_policies p ON f.instt_id = p.instt_id "
            "LEFT JOIN forest_facilities ff ON ff.instt_id = f.instt_id "
            "ORDER BY f.name"
        )
    else:
        sql = (
            "SELECT f.instt_id, f.name, p.fcfs_method, p.fcfs_detail, "
            "NULL AS water_play, NULL AS barbecue, NULL AS forest_guide "
            "FROM forests f JOIN reservation_policies p ON f.instt_id = p.instt_id "
            "ORDER BY f.name"
        )
    rows = []
    for r in conn.execute(sql):
        classified = _classify(r["fcfs_method"], r["fcfs_detail"])
        if not classified:
            continue
        kind, weekday_index, week_label = classified
        if not _opens_on(kind, weekday_index, on_date):
            continue
        rows.append(
            {
                "instt_id": r["instt_id"],
                "name": (r["name"] or "").strip(),
                "method": (r["fcfs_method"] or "").strip(),
                "week_label": week_label,
                "water_play": r["water_play"],
                "barbecue": r["barbecue"],
                "forest_guide": r["forest_guide"],
            }
        )
    return rows


def format_report(rows: list, on_date: date) -> str:
    weekday = WEEKDAYS[on_date.weekday()]
    header = (
        f"{on_date.year}년 {on_date.month}월 {on_date.day}일 ({weekday}요일)\n"
        "선착순 예약 시작 휴양림 리스트\n"
    )
    if not rows:
        return header + "\n오늘 선착순 예약이 시작되는 휴양림이 없습니다.\n"

    lines = [header]
    for i, r in enumerate(rows, start=1):
        lines.append(f"{i}. {r['name']}")
        lines.append("   " + _facility_line(r))
    return "\n".join(lines) + "\n"


_FACILITY_LABELS = [("물놀이", "water_play"), ("바베큐", "barbecue"), ("숲해설", "forest_guide")]
_MARK = {"O": "O", "X": "X", "정보없음": "-"}


def _facility_line(r: dict) -> str:
    """'물놀이(O), 바베큐(X), 숲해설(O), 6주차 예약가능' 형태의 줄을 만든다.

    시설 데이터가 아예 없으면 주차 정보만 보여준다.
    """
    parts = []
    for label, key in _FACILITY_LABELS:
        val = r.get(key)
        if val:
            parts.append(f"{label}({_MARK.get(val, '-')})")
    parts.append(f"{r['week_label']} 예약가능")
    return ", ".join(parts)
