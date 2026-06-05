from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievedDocument:
    doc_id: str
    source_table: str
    source_pk: str
    doc_type: str
    title_or_name: str | None
    text: str
    score: float
    instt_id: str | None = None
    goods_id: str | None = None


@dataclass(frozen=True)
class RagAnswer:
    question: str
    answer: str
    evidence: list[RetrievedDocument]
    model: str
    candidate: str


def format_evidence(docs: list[RetrievedDocument], max_chars_per_doc: int = 900) -> str:
    if not docs:
        return "검색된 근거가 없습니다."

    lines: list[str] = []
    for index, doc in enumerate(docs, start=1):
        title = doc.title_or_name or doc.doc_type
        text = doc.text.strip().replace("\r\n", "\n")[:max_chars_per_doc]
        lines.append(
            f"[{index}] {doc.source_table}:{doc.source_pk} "
            f"title={title} score={doc.score:.3f}\n{text}"
        )
    return "\n\n".join(lines)


def build_messages(question: str, evidence: str) -> list[dict[str, str]]:
    system = (
        "너는 국립자연휴양림 데이터 기반 안내 에이전트다. "
        "검색된 근거 안에서만 답변한다. "
        "근거가 충분하지 않으면 충분하지 않다고 말하고, 확인된 정보만 요약한다. "
        "답변에는 관련 휴양림/정책/공지 근거 번호를 함께 표시한다. "
        "가격, 할인, 예약, 시설 조건은 추측하지 않는다."
    )
    user = f"질문:\n{question}\n\n검색된 근거:\n{evidence}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
