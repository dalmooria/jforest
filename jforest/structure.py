# jforest/structure.py
"""Stage 3: 추출된 텍스트(공지 본문 + 첨부 OCR)에서 운영정보를 구조화한다.

이미지가 아닌 '텍스트'에 LLM(Vertex Gemini)을 적용해 extractedFacts 스키마로 뽑는다.
대상은 운영정보 키워드가 들어간 '고가치 공지'로 한정한다.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor

from jforest.util import now_iso

# 운영정보(요금/예약/시설/운영변경)가 담길 만한 공지를 거르는 키워드.
KEYWORDS = [
    "요금", "입장료", "사용료", "이용료", "체험료", "할인", "감면", "면제",
    "예약제외", "예약 제외", "물놀이", "바비큐", "바베큐", "숯불",
    "운영중지", "운영 중지", "휴장", "폐쇄", "공사", "퇴실", "입실",
]
_KW_RE = re.compile("|".join(map(re.escape, KEYWORDS)))

_PROMPT = """다음은 국립자연휴양림 공지사항의 본문과 첨부파일에서 추출한 텍스트입니다.
여기서 이용객에게 중요한 운영정보를 아래 JSON 스키마로만 추출하세요. 해당 정보가 없으면 null 또는 빈 배열로 두세요.
반드시 JSON만 출력하세요.

스키마:
{{
  "roomPrices": [{{"label": "구분(성수기/주중 등)", "price": 숫자(원)}}],   // 실제 금액 숫자가 명시된 경우만. 금액이 없으면 넣지 마세요(빈 배열).
  "discountPolicy": ["할인/감면 관련 문장"],
  "waterPlay": "물놀이장 운영 관련 요약 또는 null",
  "barbecue": "바비큐/숯불 관련 요약 또는 null",
  "reservationNotes": ["예약/입실/퇴실/예약제외/휴장/공사 등 운영 변경 문장"],
  "needs_review": true/false
}}

텍스트:
{text}
"""


def build_notice_text(conn, instt_id: str, twbbs_id: str, max_chars: int = 15000) -> str:
    """공지 본문(content_text)과 첨부 추출 텍스트를 합친다.

    초대형 텍스트(전국 예약제외 목록 등)는 max_chars로 잘라 LLM 출력 토큰 초과를 막는다.
    """
    n = conn.execute(
        "SELECT title, content_text FROM notices WHERE instt_id=? AND twbbs_id=?",
        (instt_id, twbbs_id),
    ).fetchone()
    parts = []
    if n:
        parts.append(n["title"] or "")
        parts.append(n["content_text"] or "")
    for a in conn.execute(
        "SELECT extracted_text FROM notice_attachments WHERE instt_id=? AND twbbs_id=?",
        (instt_id, twbbs_id),
    ):
        if a["extracted_text"]:
            parts.append(a["extracted_text"])
    return "\n".join(p for p in parts if p).strip()[:max_chars]


def select_high_value_notices(conn) -> list:
    """운영정보 키워드를 포함하고 아직 구조화되지 않은 공지 목록을 반환한다."""
    done = {(r["instt_id"], r["twbbs_id"]) for r in conn.execute(
        "SELECT instt_id, twbbs_id FROM notice_facts")}
    out = []
    for n in conn.execute("SELECT instt_id, twbbs_id FROM notices ORDER BY instt_id, twbbs_id"):
        key = (n["instt_id"], n["twbbs_id"])
        if key in done:
            continue
        text = build_notice_text(conn, key[0], key[1])
        if text and _KW_RE.search(text):
            out.append({"instt_id": key[0], "twbbs_id": key[1], "text": text})
    return out


def _strip_json(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s).strip()
    return s


def extract_facts(text: str, *, generator) -> dict:
    """generator(prompt)->JSON 문자열을 호출해 파싱한 dict를 반환한다(파싱 실패 시 예외)."""
    raw = generator(_PROMPT.format(text=text))
    return json.loads(_strip_json(raw))


def _extract_one(t, generator):
    """한 공지를 구조화해 (target, facts_json, needs_review)를 반환한다(예외는 needs_review로 격리)."""
    try:
        facts = extract_facts(t["text"], generator=generator)
        return t, json.dumps(facts, ensure_ascii=False), 1 if facts.get("needs_review") else 0
    except Exception as e:
        return t, json.dumps({"_parse_error": str(e)}, ensure_ascii=False), 1


def run_fact_extraction(conn, *, generator, model="gemini-2.5-flash", limit=None, workers=8) -> int:
    """고가치 공지를 구조화해 notice_facts에 저장한다. 처리 건수 반환.

    LLM 호출은 workers개 스레드로 동시 실행하고, DB 쓰기는 메인 스레드에서만 수행한다.
    JSON 파싱/호출 실패 시 needs_review=1로 표시하고 원문/오류를 facts_json에 보관한다.
    """
    targets = select_high_value_notices(conn)
    if limit:
        targets = targets[:limit]
    n = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for t, facts_json, needs_review in ex.map(lambda x: _extract_one(x, generator), targets):
            conn.execute(
                "INSERT OR REPLACE INTO notice_facts (instt_id, twbbs_id, facts_json, model, needs_review, extracted_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (t["instt_id"], t["twbbs_id"], facts_json, model, needs_review, now_iso()),
            )
            conn.commit()
            n += 1
    return n


def make_gemini_generator(model="gemini-2.5-flash", location="us-central1"):
    """Vertex AI Gemini 호출 generator를 만든다. GOOGLE_APPLICATION_CREDENTIALS 필요.

    프로젝트 ID는 서비스계정 JSON의 project_id 또는 GOOGLE_CLOUD_PROJECT에서 읽는다.
    """
    import os
    from google import genai

    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        cred = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if cred and os.path.exists(cred):
            with open(cred) as f:
                project = json.load(f).get("project_id")
    client = genai.Client(vertexai=True, project=project, location=location)

    def gen(prompt: str) -> str:
        resp = client.models.generate_content(
            model=model, contents=prompt,
            config={"response_mime_type": "application/json"},
        )
        return resp.text

    return gen
