# jforest/facilities.py
"""휴양림 부가정보(물놀이·바베큐·숲해설)를 LLM으로 구조화한다.

소스(검증 결과 기반):
- 물놀이/숲해설 → 공개 정보페이지(forest_intro / forest_program, 크롤러 수집)
- 바베큐 → 정보페이지엔 거의 없고, 기존 room 이용안내/공지 본문에 판정 가능한 문구가 많다
  (예: "연중 바베큐 이용이 불가능합니다").

결과는 tri-state 'O'/'X'/'정보없음' 으로 둔다(미언급을 X로 단정하지 않는다).
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor

from jforest.parsers.facilities import html_to_text
from jforest.util import now_iso

_BBQ_RE = re.compile(r"바베큐|바비큐|숯불")
_TRISTATE = {"O", "X", "정보없음"}

_PROMPT = """다음은 한 자연휴양림의 소개/프로그램/객실이용 안내 텍스트입니다.
아래 세 항목을 분류해 JSON으로만 출력하세요. 본문 근거가 없으면 반드시 "정보없음"으로 두세요(추측 금지).

- waterPlay: 물놀이/계곡/물놀이장 이용이 가능하면 "O", 금지/불가면 "X", 언급 없으면 "정보없음"
- barbecue: 바베큐/숯불 이용이 가능하면 "O", 금지/불가면 "X", 언급 없으면 "정보없음"
- forestGuide: 숲해설/생태체험/산림치유 프로그램을 운영하면 "O", 없거나 언급 없으면 "정보없음"

각 항목은 {{"v": "O|X|정보없음", "evidence": "근거 문구(없으면 빈 문자열)"}} 형식으로.
출력 스키마:
{{"waterPlay": {{"v": "", "evidence": ""}}, "barbecue": {{"v": "", "evidence": ""}}, "forestGuide": {{"v": "", "evidence": ""}}}}

텍스트:
{text}
"""


def _bbq_context(conn, instt_id: str, max_chars: int = 2500) -> str:
    """기존 데이터(객실 이용안내/공지)에서 바베큐 관련 문구만 모은다."""
    snippets = []
    for r in conn.execute(
        "SELECT u.usage_guide, u.amenities FROM rooms r "
        "JOIN room_usage_texts u ON r.goods_id = u.goods_id WHERE r.instt_id = ?",
        (instt_id,),
    ):
        for col in (r["usage_guide"], r["amenities"]):
            if col and _BBQ_RE.search(col):
                snippets.append(" ".join(col.split()))
    for r in conn.execute(
        "SELECT content_text FROM notices WHERE instt_id = ? AND content_text LIKE '%바베큐%' "
        "OR instt_id = ? AND content_text LIKE '%바비큐%' LIMIT 3",
        (instt_id, instt_id),
    ):
        if r["content_text"]:
            snippets.append(" ".join(r["content_text"].split()))
    # 중복 제거 + 길이 제한
    seen, out = set(), []
    for sn in snippets:
        key = sn[:80]
        if key in seen:
            continue
        seen.add(key)
        out.append(sn)
    return "\n".join(out)[:max_chars]


def build_facility_text(conn, instt_id: str, max_chars: int = 6000) -> str:
    """소개/프로그램 페이지 본문 + 바베큐 문구를 합쳐 LLM 입력 텍스트를 만든다."""
    parts = []
    intro = conn.execute(
        "SELECT body FROM raw_pages WHERE page_type='forest_intro' AND ref_key=?", (instt_id,)
    ).fetchone()
    if intro:
        parts.append("[휴양림소개] " + html_to_text(intro["body"])[:3000])
    prog = conn.execute(
        "SELECT body FROM raw_pages WHERE page_type='forest_program' AND ref_key=?", (instt_id,)
    ).fetchone()
    if prog:
        parts.append("[프로그램] " + html_to_text(prog["body"])[:2000])
    bbq = _bbq_context(conn, instt_id)
    if bbq:
        parts.append("[객실/공지 바베큐 안내] " + bbq)
    return "\n".join(parts).strip()[:max_chars]


def _strip_json(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s).strip()
    return s


def _norm(v) -> str:
    """LLM 출력값을 tri-state로 정규화한다."""
    if isinstance(v, dict):
        v = v.get("v")
    v = (v or "").strip()
    if v in _TRISTATE:
        return v
    if v.lower() in ("unknown", "none", "null", ""):
        return "정보없음"
    return "정보없음"


def extract_facilities(text: str, *, generator) -> dict:
    """generator(prompt)->JSON 문자열을 호출해 시설 dict를 반환한다.

    반환: {water_play, barbecue, forest_guide, *_evidence}
    """
    raw = generator(_PROMPT.format(text=text))
    data = json.loads(_strip_json(raw))

    def field(key):
        node = data.get(key) or {}
        evid = node.get("evidence", "") if isinstance(node, dict) else ""
        return _norm(node), (evid or "")

    wp, wpe = field("waterPlay")
    bq, bqe = field("barbecue")
    fg, fge = field("forestGuide")
    return {
        "water_play": wp,
        "barbecue": bq,
        "forest_guide": fg,
        "water_play_evidence": wpe,
        "barbecue_evidence": bqe,
        "forest_guide_evidence": fge,
    }


def _extract_one(item, generator):
    """미리 만든 (instt_id, text)를 LLM에 보낸다. DB 접근 없음(스레드 안전)."""
    instt_id, text = item
    try:
        return instt_id, extract_facilities(text, generator=generator), 0
    except Exception as e:
        return instt_id, {"_parse_error": str(e)}, 1


def run_facility_extraction(conn, *, generator, model="gemini-2.5-flash", limit=None, workers=8) -> int:
    """수집된 정보페이지가 있는 휴양림을 구조화해 forest_facilities에 저장한다. 처리 건수 반환.

    LLM 호출만 스레드로 돌리고(DB 미접근), 텍스트 조립·DB 쓰기는 메인 스레드에서 한다.
    """
    targets = [
        r["instt_id"]
        for r in conn.execute(
            "SELECT DISTINCT ref_key AS instt_id FROM raw_pages "
            "WHERE page_type IN ('forest_intro', 'forest_program') ORDER BY ref_key"
        )
    ]
    if limit:
        targets = targets[:limit]

    # 메인 스레드에서 텍스트 조립(빈 텍스트는 제외)
    items = [(iid, build_facility_text(conn, iid)) for iid in targets]
    items = [it for it in items if it[1]]

    n = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = ex.map(lambda it: _extract_one(it, generator), items)
        for instt_id, facts, needs_review in results:
            if facts is None:
                continue
            if needs_review:
                conn.execute(
                    "INSERT OR REPLACE INTO forest_facilities "
                    "(instt_id, model, needs_review, extracted_at) VALUES (?, ?, 1, ?)",
                    (instt_id, model, now_iso()),
                )
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO forest_facilities "
                    "(instt_id, water_play, barbecue, forest_guide, "
                    "water_play_evidence, barbecue_evidence, forest_guide_evidence, "
                    "model, needs_review, extracted_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
                    (instt_id, facts["water_play"], facts["barbecue"], facts["forest_guide"],
                     facts["water_play_evidence"], facts["barbecue_evidence"],
                     facts["forest_guide_evidence"], model, now_iso()),
                )
            conn.commit()
            n += 1
    return n
