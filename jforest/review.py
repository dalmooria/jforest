# jforest/review.py
"""needs_review 검수: 주관적 모델 플래그를 객관 규칙으로 재검증하고 검수 큐를 내보낸다.

Gemini가 정확히 추출하고도 needs_review=true로 표시하는 노이즈가 많다. 여기서는
가격/추출여부/파싱오류 같은 객관 기준으로 needs_review를 다시 계산해 진짜 문제만 남긴다.
"""
import json


def validate_facts(facts: dict) -> tuple:
    """(needs_review, issues) 반환. 객관적 문제가 있으면 needs_review=True."""
    issues = []
    if "_parse_error" in facts:
        return True, ["LLM 응답 파싱 실패"]
    # 가격 타당성: 0원(무료)·고액(장기패키지)은 정상이므로 None/비숫자/음수만 문제로 본다.
    for p in facts.get("roomPrices") or []:
        price = p.get("price") if isinstance(p, dict) else None
        if isinstance(price, bool) or not isinstance(price, (int, float)) or price < 0:
            issues.append(f"비정상 price: {price!r}")
    # 빈 결과는 비-운영 공지(키워드 우연 매칭)가 대부분이라 검수 대상으로 보지 않는다.
    return (len(issues) > 0), issues


def run_revalidation(conn) -> dict:
    """모든 notice_facts의 needs_review를 객관 검증으로 재계산한다. {flagged, cleared} 반환."""
    flagged = cleared = 0
    for r in list(conn.execute("SELECT instt_id, twbbs_id, facts_json, needs_review FROM notice_facts")):
        try:
            facts = json.loads(r["facts_json"])
        except Exception:
            facts = {"_parse_error": "json load 실패"}
        need, _ = validate_facts(facts)
        new = 1 if need else 0
        if new != r["needs_review"]:
            conn.execute(
                "UPDATE notice_facts SET needs_review=? WHERE instt_id=? AND twbbs_id=?",
                (new, r["instt_id"], r["twbbs_id"]),
            )
        if new:
            flagged += 1
        else:
            cleared += 1
    conn.commit()
    return {"flagged": flagged, "cleared": cleared}


def export_review_queue(conn, path: str) -> int:
    """needs_review=1 인 항목을 원문/추출/이슈와 함께 JSONL로 내보낸다. 건수 반환."""
    n = 0
    with open(path, "w", encoding="utf-8") as fh:
        for r in conn.execute(
            "SELECT instt_id, twbbs_id, facts_json FROM notice_facts WHERE needs_review=1 ORDER BY instt_id, twbbs_id"
        ):
            try:
                facts = json.loads(r["facts_json"])
            except Exception:
                facts = {"_parse_error": "json load 실패"}
            _, issues = validate_facts(facts)
            note = conn.execute(
                "SELECT title, content_text FROM notices WHERE instt_id=? AND twbbs_id=?",
                (r["instt_id"], r["twbbs_id"]),
            ).fetchone()
            rec = {
                "instt_id": r["instt_id"],
                "twbbs_id": r["twbbs_id"],
                "title": (note["title"] if note else None),
                "content_text": (note["content_text"] if note else None),
                "facts": facts,
                "issues": issues,
            }
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    return n
