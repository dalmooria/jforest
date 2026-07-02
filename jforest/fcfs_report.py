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
import unicodedata
from datetime import date, timedelta

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
        # 월간 오픈일은 휴양림마다 다르다(1·5·7·10·11일 등) → 본문에서 파싱, 없으면 1일.
        mon = _DETAIL_MONTHLY.search(detail)
        day = int(mon.group(1)) if mon else 1
        return "monthly", day, "익월 말일까지"

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


_WEEKNUM_LABEL = re.compile(r"(\d+)주차")


def _reservable_label(kind, week_label: str, on_date: date) -> str:
    """예약가능 시점을 사람이 읽는 문구로 만든다.

    주간: 오픈일(수)부터 N주 창이 열리므로 마지막 예약가능일 = 오픈일 + N*7 - 1일(화).
          라이브 예약 캘린더(useDtList)로 검증됨(예: 6/10 오픈 → 6주차 = ~7/21 화).
    월간: 휴양림별 편차가 커서 정책 문구('익월 말일까지')를 그대로 둔다.
    """
    if kind == "weekly":
        m = _WEEKNUM_LABEL.search(week_label or "")
        if m:
            n = int(m.group(1))
            last = on_date + timedelta(days=n * 7 - 1)
            return f"{week_label}(~{last.month}/{last.day} {WEEKDAYS[last.weekday()]}) 예약가능"
    return f"{week_label} 예약가능"


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
    genmap = _general_open_map(conn)
    rows = []
    for r in conn.execute(sql):
        gen = genmap.get(r["instt_id"])
        for s in _fcfs_open_specs(r["fcfs_method"], r["fcfs_detail"], gen):
            if not _opens_on(s["kind"], s["key"], on_date):
                continue
            if s["type_label"] == "일반전환":
                reservable = "지역주민 미신청·취소분 일반오픈"
            else:
                reservable = _reservable_label(s["kind"], s["week_label"], on_date)
            if s["conf"] == "추정":
                reservable += " (오픈일 추정)"
            rows.append(
                {
                    "instt_id": r["instt_id"],
                    "name": (r["name"] or "").strip(),
                    "method": (r["fcfs_method"] or "").strip(),
                    "kind": s["kind"],  # "weekly"(매주 반복) | "monthly"(오늘 지정 오픈)
                    "week_label": s["week_label"] or "",
                    "reservable_label": reservable,
                    "water_play": r["water_play"],
                    "barbecue": r["barbecue"],
                    "forest_guide": r["forest_guide"],
                }
            )
    return rows


def _numbered(rows: list) -> list:
    lines = []
    for i, r in enumerate(rows, start=1):
        lines.append(f"{i}. {r['name']}")
        lines.append("   " + _facility_line(r))
    return lines


def format_report(rows: list, on_date: date) -> str:
    """월간(오늘 지정 오픈)을 앞에 강조하고, 주간(매주 반복 오픈)을 뒤에 묶어 보여준다."""
    weekday = WEEKDAYS[on_date.weekday()]
    header = (
        f"{on_date.year}년 {on_date.month}월 {on_date.day}일 ({weekday}요일)\n"
        "선착순 예약 시작 휴양림 리스트\n"
    )
    if not rows:
        return header + "\n오늘 선착순 예약이 시작되는 휴양림이 없습니다.\n"

    monthly = [r for r in rows if r["kind"] == "monthly"]
    weekly = [r for r in rows if r["kind"] == "weekly"]

    lines = [header]
    # 월간: '오늘이 지정 오픈일'인 곳 — 오늘만의 특별 오픈이라 앞에 강조
    lines.append(f"\n★ 오늘 지정 오픈 (월간) — {len(monthly)}곳")
    lines += _numbered(monthly) if monthly else ["  (오늘이 지정 오픈일인 월간 휴양림 없음)"]
    # 주간: 매주 같은 요일 반복 오픈 — 참고용으로 뒤에
    lines.append(f"\n· 매주 {weekday}요일 반복 오픈 (주간) — {len(weekly)}곳")
    lines += _numbered(weekly) if weekly else ["  (해당 없음)"]
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
    parts.append(r.get("reservable_label") or f"{r['week_label']} 예약가능")
    return ", ".join(parts)


# ─────────────────────────────────────────────────────────────────────────
# Open Report (v2): 선착순 + 추첨 + 지역주민 + 일반오픈(15일)  (설계 §3)
# ─────────────────────────────────────────────────────────────────────────

SIDO = {1: "경기·인천", 2: "강원", 3: "충북", 4: "충남·대전", 5: "전북",
        6: "전남·광주", 7: "경북·대구", 8: "경남·부산·울산", 9: "제주"}
# 지리적 정렬 순서(수도권→강원→충청→…→제주). 지역명 가나다 대신 사용.
_REGION_ORDER = {name: i for i, name in SIDO.items()}

# rule_id → type_group. 101(선착순)은 reservation_policies로만 처리하므로 여기 제외.
# 103=성수기(별도), 106/107/108/112/211=제외(자격제한).
RULE_GROUP = {"102": "추첨", "111": "추첨",
              "104": "지역주민", "105": "지역주민"}
RULE_LABEL = {"102": "주말추첨", "111": "월추첨",
              "104": "지역주민 우대추첨", "105": "지역주민 우선"}
# 국립 표준 오픈일 상수 폴백 (파싱 실패 시). (kind, day, time)
NATIONAL_DEFAULT = {"102": ("monthly", 4, "오전 9시"), "111": ("monthly", 1, "오전 9시")}
GENERAL_OPEN = ("monthly", 15, "오전 9시")  # 일반오픈(미선정분): 102 보유 휴양림

SEASONAL_NOTE = ("성수기추첨: 매년 5월말~6월 접수 / 이용 7·8월 / 45개 국립휴양림 "
                 "— 접수기간은 숲나들e 공지 확인")

_GROUP_ORDER = {"선착순": 0, "추첨": 1, "지역주민": 2}

_ANCHORS = ["예약 신청", "예약신청", "신청 접수 기간", "신청접수기간",
            "추첨 예약 신청", "추첨예약신청", "접수 기간", "우선 예약", "우선예약"]
_SECTION_MARK = re.compile(r"[○※▶■]|(?<!\d)-\s")
_RE_MONTHLY = re.compile(r"매[월달]\s*(\d{1,2})\s*일")
_RE_WEEKLY = re.compile(r"매주\s*([월화수목금토일])\s*요일")
_RE_WEEKLY_BARE = re.compile(r"^[\s:]*([월화수목금토일])요일")
_RE_TIME_AMPM = re.compile(r"(오전|오후)\s*(\d{1,2})\s*시")
_RE_TIME_HHMM = re.compile(r"(\d{1,2})\s*:\s*(\d{2})")


def _region(sido_code) -> str:
    return SIDO.get(sido_code, "기타")


def _normalize(text: str) -> str:
    """NFKC 정규화 + 모든 공백 단일화(HWP 추출의 글자단위 줄바꿈 제거)."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text or ""))


def _anchored_segment(norm_text: str):
    """가장 이른 '예약신청' 앵커부터 다음 섹션 마커 직전까지의 세그먼트."""
    best_i, seg = None, None
    for a in _ANCHORS:
        i = norm_text.find(a)
        if i != -1 and (best_i is None or i < best_i):
            after = norm_text[i + len(a):]
            m = _SECTION_MARK.search(after)
            seg = after[: m.start()] if m else after[:80]
            best_i = i
    return seg


def _fmt_time(hour: int, minute: int = 0) -> str:
    ampm = "오전" if hour < 12 else "오후"
    h12 = hour if hour <= 12 else hour - 12
    if h12 == 0:
        h12 = 12
    return f"{ampm} {h12}시" + (f" {minute}분" if minute else "")


def _match_time(seg: str):
    if not seg:
        return None
    m = _RE_TIME_AMPM.search(seg)
    if m:
        h = int(m.group(2))
        return _fmt_time(h + 12 if m.group(1) == "오후" and h < 12 else h)
    m = _RE_TIME_HHMM.search(seg)
    if m:
        return _fmt_time(int(m.group(1)), int(m.group(2)))
    return None


def parse_open_event(detail_text: str, rule_id: str):
    """추첨/지역주민 예약창 오픈일·시각을 파싱한다.

    반환: {"kind","key","open_time","time_conf","conf"} 또는 None(날짜 파싱 실패).
    파싱 실패 시 국립 표준 상수 폴백을 시도한다.
    """
    seg = _anchored_segment(_normalize(detail_text))
    kind = key = None
    if seg:
        m = _RE_WEEKLY.search(seg) or _RE_WEEKLY_BARE.search(seg)
        if m:
            kind, key = "weekly", _WD_INDEX[m.group(1)]
        else:
            m = _RE_MONTHLY.search(seg)
            if m:
                kind, key = "monthly", int(m.group(1))
    if kind is None:
        d = NATIONAL_DEFAULT.get(rule_id)
        if not d:
            return None
        return {"kind": d[0], "key": d[1], "open_time": d[2],
                "time_conf": "확정", "conf": "추정"}
    tm = _match_time(seg)
    return {"kind": kind, "key": key, "open_time": tm,
            "time_conf": "확정" if tm else "미상", "conf": "확정"}


def _open_time_from_fcfs(fcfs_detail: str):
    """선착순 fcfs_detail 본문에서 오픈 시각을 뽑는다(국립은 대개 '오전 9시')."""
    return _match_time(_normalize(fcfs_detail))


# ─── 지역주민 우선분 → 일반 선착순 전환일 ────────────────────────────────
# 시군 휴양림은 매월 1~N일 지역주민 우선예약 후, 미신청·취소분이 '전환일'에 일반에게
# 열린다. 이 전환일이 진짜 '일반 선착순 오픈일'인데 fcfs_method(rule 101) 본문 첫 날짜는
# 대개 지역주민 우선일(1일)이라 _classify가 이를 놓친다 → policy_details에서 보정한다.
_GENERAL_OPEN = re.compile(
    r"(?:선착순\s*(?:일반예약\s*)?전환|일반\s*(?:예약)?\s*(?:전환|오픈)|일반고객\s*오픈)"
    r"\s*[:：]?\s*(?:매[월달]\s*)?(\d{1,2})\s*일"
)
# 시군 지역주민 규칙(우선/우대추첨/월추첨)이 전환일을 담는다. 107(산림복지바우처)은
# 전국 공통 '매월 15일' 폴백이라 시군 규칙이 없을 때만 사용한다.
_GEN_OPEN_PRIMARY = ("104", "105", "111")
_GEN_OPEN_FALLBACK = ("107",)


_RE_TIME_BARE = re.compile(r"(\d{1,2})\s*시")  # 오전/오후·콜론 없는 24시제 '14시'


def _match_bare_hour(seg: str):
    """'14시', '09시'처럼 오전/오후 표기 없는 24시제 시각을 읽는다(전환일 본문에 흔함)."""
    if not seg:
        return None
    m = _RE_TIME_BARE.search(seg)
    if not m:
        return None
    h = int(m.group(1))
    return _fmt_time(h) if h <= 23 else None


def _extract_general_open(text: str):
    """'선착순 전환 / 일반(예약·고객) 전환·오픈 : 매월 N일 [시각]' → (day, open_time) 또는 None."""
    norm = _normalize(text)
    m = _GENERAL_OPEN.search(norm)
    if not m:
        return None
    seg = norm[m.end(): m.end() + 20]
    return int(m.group(1)), _match_time(seg) or _match_bare_hour(seg)


def _general_open_map(conn) -> dict:
    """{instt_id: (day, open_time, rule_id)} — 지역주민 우선분이 일반에게 열리는 전환일.

    시군 규칙(104/105/111)을 바우처(107)보다 우선하고, 여러 개면 가장 이른 날을 쓴다.
    """
    prim, fallb = {}, {}
    for r in conn.execute(
        "SELECT instt_id, rule_id, detail_text FROM reservation_policy_details"
    ):
        g = _extract_general_open(r["detail_text"])
        if not g:
            continue
        day, tm = g
        if r["rule_id"] in _GEN_OPEN_PRIMARY:
            bucket = prim
        elif r["rule_id"] in _GEN_OPEN_FALLBACK:
            bucket = fallb
        else:
            continue
        cur = bucket.get(r["instt_id"])
        if cur is None or day < cur[0]:
            bucket[r["instt_id"]] = (day, tm, r["rule_id"])
    out = dict(fallb)
    out.update(prim)  # 시군 전환일이 있으면 바우처(107)를 덮어쓴다
    return out


def _is_fallback_monthly(fcfs_method, fcfs_detail) -> bool:
    """'익월말'인데 본문에 '매월 N일'이 없어 오픈일을 1일로 임의추정한 경우."""
    return ((fcfs_method or "").strip() == "익월말"
            and not _DETAIL_MONTHLY.search(fcfs_detail or ""))


def _weekly_general_open(gen):
    """주간 휴양림에 '추가'할 일반전환일인지 판정한다.

    시군(104/105/111)은 항상 추가한다. 바우처(107)는 '매월 15일'만 build_open_events
    (3)단계와 중복이라 제외하고, 그 외 특정일(6·8·16일 등)은 추가한다.
    """
    if not gen:
        return None
    day, _gtm, rule = gen
    if rule in _GEN_OPEN_PRIMARY:
        return gen
    if rule in _GEN_OPEN_FALLBACK and day != 15:
        return gen
    return None


def _fcfs_open_specs(fcfs_method, fcfs_detail, gen):
    """선착순 정책 1건 → 이 정책이 여는 오픈 이벤트 스펙 목록(날짜 무관).

    - 월간: 분류일(대개 1일=지역주민 우선)을 진짜 전환일(gen)로 '교체'한다.
    - 주간: 매주 요일 창은 유지하고, 전환일이 따로 있으면 '일반전환' 이벤트를 '추가'한다.
    스펙의 conf는 오픈일 신뢰도('확정' | '추정'). 근거 없는 1일 폴백만 '추정'.
    """
    c = _classify(fcfs_method, fcfs_detail)
    if not c:
        return []
    kind, key, week_label = c
    specs = []
    if kind == "monthly":
        if gen:
            day, gtm, _rule = gen
            # 전환일 본문에서 뽑은 시각만 신뢰한다. fcfs_detail 폴백은 예약대기 등
            # 무관한 시각('24:00' 등)을 오탐하므로 쓰지 않고, 없으면 '미상'으로 둔다.
            specs.append({"kind": "monthly", "key": day, "week_label": week_label,
                          "open_time": gtm, "type_label": "선착순", "conf": "확정"})
        else:
            specs.append({"kind": "monthly", "key": key, "week_label": week_label,
                          "open_time": _open_time_from_fcfs(fcfs_detail),
                          "type_label": "선착순",
                          "conf": "추정" if _is_fallback_monthly(fcfs_method, fcfs_detail)
                                  else "확정"})
    else:  # weekly
        specs.append({"kind": "weekly", "key": key, "week_label": week_label,
                      "open_time": _open_time_from_fcfs(fcfs_detail),
                      "type_label": "선착순", "conf": "확정"})
        add = _weekly_general_open(gen)
        if add:
            day, gtm, _rule = add
            specs.append({"kind": "monthly", "key": day, "week_label": None,
                          "open_time": gtm, "type_label": "일반전환", "conf": "확정"})
    return specs


def _fac_mark(val, needs_review) -> str:
    if needs_review:
        return "△"
    return {"O": "O", "X": "X"}.get(val, "△")


def _facilities_map(conn) -> dict:
    if not _has_facilities(conn):
        return {}
    out = {}
    for r in conn.execute(
        "SELECT instt_id, water_play, barbecue, forest_guide, needs_review "
        "FROM forest_facilities"
    ):
        out[r["instt_id"]] = (
            _fac_mark(r["water_play"], r["needs_review"]),
            _fac_mark(r["barbecue"], r["needs_review"]),
            _fac_mark(r["forest_guide"], r["needs_review"]),
        )
    return out


def _forest_meta(conn) -> dict:
    return {r["instt_id"]: (r["name"], _region(r["sido_code"]), r["homepage_url"])
            for r in conn.execute(
                "SELECT instt_id, name, sido_code, homepage_url FROM forests")}


def _room_summary_map(conn) -> dict:
    """forest_room_summary(서빙 스냅샷에만 존재) → {iid: (room_count, price_min, price_max)}."""
    if not conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='forest_room_summary'"
    ).fetchone():
        return {}
    return {r["instt_id"]: (r["room_count"], r["price_min"], r["price_max"])
            for r in conn.execute("SELECT * FROM forest_room_summary")}


def _active_blocks_map(conn, on_date: date) -> dict:
    """on_date에 활성인 예약불가 블록(needs_review=0) → {instt_id: [block, …]}."""
    if not conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='reservation_blocks'"
    ).fetchone():
        return {}
    d = on_date.isoformat()
    out = {}
    for r in conn.execute(
        "SELECT instt_id, alert_type, start_date, end_date, reason FROM reservation_blocks "
        "WHERE needs_review=0 AND start_date<=? AND end_date>=? ORDER BY end_date", (d, d)
    ):
        out.setdefault(r["instt_id"], []).append({
            "alert_type": r["alert_type"], "start_date": r["start_date"],
            "end_date": r["end_date"], "reason": r["reason"]})
    return out


def _reservable(group, type_label, kind, week_label, on_date, confidence) -> str:
    if confidence == "미상":
        return "일정 확인 필요"
    if group == "선착순":
        if type_label.startswith("일반오픈"):
            return "추첨 미선정·취소분 오픈"
        if type_label.startswith("일반전환"):
            return "지역주민 미신청·취소분 일반오픈"
        if kind == "weekly":
            return _reservable_label(kind, week_label, on_date)
        return "익월 말일 이용분 예약가능"
    if group == "추첨":
        return "다음달 이용분 접수 시작"
    if group == "지역주민":
        return "지역주민 우선 접수"
    return "예약 오픈"


def _event(instt_id, meta, fac, summary, blocks, group, type_label, kind, week_label,
           open_time, time_conf, on_date, conf):
    name, region, homepage = meta.get(instt_id, ("(미상)", "기타", None))
    wp, bbq, fg = fac.get(instt_id, ("△", "△", "△"))
    room_count, price_min, price_max = summary.get(instt_id, (None, None, None))
    return {
        "instt_id": instt_id, "name": (name or "").strip(), "region": region,
        "homepage_url": homepage,
        "type_group": group, "type_label": type_label,
        "kind": kind, "open_time": open_time, "time_confidence": time_conf,
        "reservable_label": _reservable(group, type_label, kind, week_label, on_date, conf),
        "confidence": conf,
        "water_play": wp, "barbecue": bbq, "forest_guide": fg,
        "room_count": room_count, "price_min": price_min, "price_max": price_max,
        "alerts": blocks.get(instt_id, []),
    }


def _merge_and_sort(events):
    """(instt_id, group, open_time) 병합 → 그룹/미상/지역/이름 정렬."""
    merged = {}
    for e in events:
        k = (e["instt_id"], e["type_group"], e["open_time"])
        if k in merged:
            labels = merged[k]["type_label"].split("·")
            if e["type_label"] not in labels:
                merged[k]["type_label"] += "·" + e["type_label"]
        else:
            merged[k] = e

    def key(e):
        return (_GROUP_ORDER.get(e["type_group"], 9),
                1 if e["confidence"] == "미상" else 0,
                _REGION_ORDER.get(e["region"], 99), e["name"])

    return sorted(merged.values(), key=key)


def build_open_events(conn, on_date: date) -> list:
    """on_date에 예약창이 열리는 채널(이벤트) 목록을 반환한다(병합·정렬 완료)."""
    meta = _forest_meta(conn)
    fac = _facilities_map(conn)
    summ = _room_summary_map(conn)
    blocks = _active_blocks_map(conn, on_date)
    events = []

    # (1) 선착순 — reservation_policies + _classify, 전환일은 policy_details로 보정
    genmap = _general_open_map(conn)
    for r in conn.execute(
        "SELECT instt_id, fcfs_method, fcfs_detail FROM reservation_policies"
    ):
        gen = genmap.get(r["instt_id"])
        for s in _fcfs_open_specs(r["fcfs_method"], r["fcfs_detail"], gen):
            if not _opens_on(s["kind"], s["key"], on_date):
                continue
            tm = s["open_time"]
            events.append(_event(r["instt_id"], meta, fac, summ, blocks, "선착순",
                                 s["type_label"], s["kind"], s["week_label"],
                                 tm, "확정" if tm else "미상", on_date, s["conf"]))

    # (2) 추첨·지역주민 — reservation_policy_details
    for r in conn.execute(
        "SELECT instt_id, rule_id, detail_text FROM reservation_policy_details"
    ):
        group = RULE_GROUP.get(r["rule_id"])
        if not group:
            continue
        pe = parse_open_event(r["detail_text"], r["rule_id"])
        if pe is None:
            continue  # 미상은 build_open_report의 별도 리스트로 (날짜 오탐 방지)
        if not _opens_on(pe["kind"], pe["key"], on_date):
            continue
        events.append(_event(r["instt_id"], meta, fac, summ, blocks, group,
                             RULE_LABEL.get(r["rule_id"], group),
                             pe["kind"], None, pe["open_time"], pe["time_conf"],
                             on_date, pe["conf"]))

    # (3) 일반오픈(미선정분) — 102 보유 휴양림, 매월 15일
    if on_date.day == GENERAL_OPEN[1]:
        for r in conn.execute(
            "SELECT DISTINCT instt_id FROM reservation_policy_details WHERE rule_id='102'"
        ):
            events.append(_event(r["instt_id"], meta, fac, summ, blocks, "선착순",
                                 "일반오픈(미선정분)", "general", None,
                                 GENERAL_OPEN[2], "확정", on_date, "추정"))

    return _merge_and_sort(events)


def collect_uncertain(conn) -> list:
    """오픈일 파싱 불가한 추첨/지역주민 채널(날짜 무관 참고용). (instt_id,group) 유일."""
    meta = _forest_meta(conn)
    seen, out = set(), []
    for r in conn.execute(
        "SELECT instt_id, rule_id, detail_text FROM reservation_policy_details"
    ):
        group = RULE_GROUP.get(r["rule_id"])
        if not group:
            continue
        if parse_open_event(r["detail_text"], r["rule_id"]) is not None:
            continue
        k = (r["instt_id"], group)
        if k in seen:
            continue
        seen.add(k)
        name, region, _hp = meta.get(r["instt_id"], ("(미상)", "기타", None))
        out.append({"instt_id": r["instt_id"], "name": (name or "").strip(),
                    "region": region, "type_group": group,
                    "type_label": RULE_LABEL.get(r["rule_id"], group)})
    out.sort(key=lambda e: (_GROUP_ORDER.get(e["type_group"], 9),
                            _REGION_ORDER.get(e["region"], 99), e["name"]))
    return out


# 대부분의 날은 오픈이 없다(오픈은 수/1일/4일/15일에 집중) → 다가오는 주요 오픈일 안내.
_UPCOMING_SPECS = [
    ("선착순 (국립 주간)", "weekly", 2, "오전 9시"),   # 수요일
    ("월간 (익월말·월추첨)", "monthly", 1, "오전 9시"),
    ("주말추첨 접수", "monthly", 4, "오전 9시"),
    ("일반오픈 (미선정분)", "monthly", 15, "오전 9시"),
]


def _next_date(start: date, pred, within: int = 45):
    d = start
    for _ in range(within):
        if pred(d):
            return d
        d += timedelta(days=1)
    return None


def upcoming_openings(on_date: date) -> list:
    """on_date 이후 다가오는 주요 오픈일(D-day)."""
    out = []
    for label, kind, key, tm in _UPCOMING_SPECS:
        if kind == "weekly":
            pred = (lambda d, k=key: d.weekday() == k)
        else:
            pred = (lambda d, k=key: d.day == k)
        d = _next_date(on_date + timedelta(days=1), pred)
        if d:
            out.append({"label": label, "date": d.isoformat(),
                        "weekday": WEEKDAYS[d.weekday()], "dday": (d - on_date).days,
                        "open_time": tm})
    out.sort(key=lambda x: x["dday"])
    return out


def active_restrictions(conn, on_date: date) -> list:
    """on_date에 예약불가/공사/휴관 등 제한이 걸린 휴양림(오픈 여부 무관)."""
    meta = _forest_meta(conn)
    out = []
    for iid, blks in _active_blocks_map(conn, on_date).items():
        name, region, _hp = meta.get(iid, ("(미상)", "기타", None))
        b = blks[0]  # 가장 이른 종료
        out.append({"instt_id": iid, "name": (name or "").strip(), "region": region,
                    "alert_type": b["alert_type"], "end_date": b["end_date"],
                    "reason": b["reason"], "count": len(blks)})
    out.sort(key=lambda e: (_REGION_ORDER.get(e["region"], 99), e["name"]))
    return out


def build_open_report(conn, on_date: date) -> dict:
    """API/JSON용 리포트 dict. 타입별 그룹 + 미상 참고 + 제한 안내 + 성수기 안내."""
    events = build_open_events(conn, on_date)
    groups = []
    for g in ("선착순", "추첨", "지역주민"):
        evs = [e for e in events if e["type_group"] == g]
        if evs:
            groups.append({"type_group": g, "count": len(evs), "events": evs})
    return {
        "date": on_date.isoformat(),
        "weekday": WEEKDAYS[on_date.weekday()],
        "total": len(events),
        "groups": groups,
        "uncertain": collect_uncertain(conn),
        "upcoming": upcoming_openings(on_date),
        "restrictions": active_restrictions(conn, on_date),
        "seasonal_note": SEASONAL_NOTE,
    }


def format_open_report(report: dict) -> str:
    """build_open_report(dict)를 터미널용 텍스트로 렌더한다(CLI/디버그)."""
    lines = [f"{report['date']} ({report['weekday']}) 예약 오픈 — 총 {report['total']}곳"]
    if report["total"] == 0:
        lines.append("  (이 날짜에 열리는 휴양림 없음)")
    for g in report["groups"]:
        lines.append(f"\n━━ {g['type_group']} ({g['count']}) ━━")
        for e in g["events"]:
            t = e["open_time"] or "시각미상"
            fac = f"물{e['water_play']}바{e['barbecue']}숲{e['forest_guide']}"
            tag = "" if e["confidence"] == "확정" else f" [{e['confidence']}]"
            lines.append(f"  {e['name']} / {e['region']} · {e['type_label']} · {t} · "
                         f"{fac} · {e['reservable_label']}{tag}")
    unc = report.get("uncertain") or []
    if unc:
        lines.append(f"\n⚠ 일정 확인 필요 {len(unc)}곳: "
                     + ", ".join(f"{u['name']}({u['type_group']})" for u in unc[:10])
                     + (" …" if len(unc) > 10 else ""))
    lines.append(f"\n· {report['seasonal_note']}")
    return "\n".join(lines) + "\n"
