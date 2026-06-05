from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, replace
from typing import Protocol

from jforest.embeddings import Embedder, get_embedder
from jforest.vector_index import QdrantLocalIndex


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
    instt_name: str | None = None


@dataclass(frozen=True)
class RagAnswer:
    question: str
    answer: str
    evidence: list[RetrievedDocument]
    model: str
    candidate: str


class VectorSearch(Protocol):
    def search(self, vector: list[float], limit: int) -> list[dict]:
        ...


class AnswerGenerator(Protocol):
    model: str

    def generate(self, messages: list[dict[str, str]]) -> str:
        ...


class Reranker(Protocol):
    def rerank(
        self, query: str, docs: list["RetrievedDocument"], top_k: int
    ) -> list["RetrievedDocument"]:
        ...


class BgeReranker:
    """Cross-encoder reranker. Scores each (query, doc.text) pair jointly, which
    resolves the multi-concept dilution that bi-encoder vector search misses
    (e.g. '<forest> 바베큐' where a forest has many rooms)."""

    def __init__(self, model: str = "BAAI/bge-reranker-v2-m3"):
        from sentence_transformers import CrossEncoder

        self.model_name = model
        self.model = CrossEncoder(model)

    def rerank(
        self, query: str, docs: list["RetrievedDocument"], top_k: int
    ) -> list["RetrievedDocument"]:
        if not docs:
            return []
        scores = self.model.predict([(query, doc.text) for doc in docs])
        ranked = sorted(zip(docs, scores), key=lambda pair: pair[1], reverse=True)
        return [replace(doc, score=float(score)) for doc, score in ranked[:top_k]]


class NameResolver(Protocol):
    def resolve(self, instt_ids: list[str]) -> dict[str, str]:
        ...


class SqliteForestNames:
    def __init__(self, db_path: str = "data/jforest.db"):
        self.db_path = db_path

    def resolve(self, instt_ids: list[str]) -> dict[str, str]:
        if not instt_ids or not os.path.exists(self.db_path):
            return {}
        placeholders = ",".join("?" for _ in instt_ids)
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                f"SELECT instt_id, name FROM forests WHERE instt_id IN ({placeholders})",
                instt_ids,
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
        finally:
            conn.close()
        return {row[0]: row[1] for row in rows}


class OpenAIAnswerGenerator:
    def __init__(self, model: str = "gpt-4.1-mini"):
        from openai import OpenAI

        self.model = model
        self.client = OpenAI(timeout=120.0)

    def generate(self, messages: list[dict[str, str]]) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.2,
        )
        content = response.choices[0].message.content
        return content or ""


def _doc_from_payload(payload: dict) -> RetrievedDocument:
    return RetrievedDocument(
        doc_id=str(payload.get("doc_id") or ""),
        source_table=str(payload.get("source_table") or ""),
        source_pk=str(payload.get("source_pk") or ""),
        doc_type=str(payload.get("doc_type") or ""),
        title_or_name=payload.get("title_or_name"),
        text=str(payload.get("text") or ""),
        score=float(payload.get("score") or 0.0),
        instt_id=payload.get("instt_id"),
        goods_id=payload.get("goods_id"),
    )


def format_evidence(docs: list[RetrievedDocument], max_chars_per_doc: int = 900) -> str:
    if not docs:
        return "검색된 근거가 없습니다."

    lines: list[str] = []
    for index, doc in enumerate(docs, start=1):
        title = doc.title_or_name or doc.doc_type
        text = doc.text.strip().replace("\r\n", "\n")[:max_chars_per_doc]
        forest = f" 휴양림={doc.instt_name}" if doc.instt_name else ""
        lines.append(
            f"[{index}] {doc.source_table}:{doc.source_pk}{forest} "
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


def answer_question(
    question: str,
    *,
    candidate_name: str = "openai-large",
    qdrant_root: str = "data/qdrant",
    collection: str = "jforest",
    limit: int = 8,
    chat_model: str = "gpt-4.1-mini",
    db_path: str = "data/jforest.db",
    rerank_candidates: int = 50,
    embedder: Embedder | None = None,
    index: VectorSearch | None = None,
    generator: AnswerGenerator | None = None,
    name_resolver: NameResolver | None = None,
    reranker: Reranker | None = None,
) -> RagAnswer:
    embedder = embedder or get_embedder(candidate_name)
    candidate = embedder.candidate
    index = index or QdrantLocalIndex(
        root=f"{qdrant_root}/{candidate.name}",
        collection=collection,
        dimension=candidate.dimension,
    )
    generator = generator or OpenAIAnswerGenerator(model=chat_model)
    name_resolver = name_resolver or SqliteForestNames(db_path)

    # With a reranker, pull a wider candidate pool then let the cross-encoder
    # pick the final `limit`; without one, search returns `limit` directly.
    search_limit = max(limit, rerank_candidates) if reranker else limit
    vector = embedder.embed_texts([question])[0]
    payloads = index.search(vector, limit=search_limit)
    docs = [_doc_from_payload(payload) for payload in payloads]
    if reranker:
        docs = reranker.rerank(question, docs, limit)
    instt_ids = sorted({doc.instt_id for doc in docs if doc.instt_id})
    names = name_resolver.resolve(instt_ids) if instt_ids else {}
    docs = [replace(doc, instt_name=names.get(doc.instt_id)) for doc in docs]
    messages = build_messages(question, format_evidence(docs))
    answer = generator.generate(messages)
    return RagAnswer(
        question=question,
        answer=answer,
        evidence=docs,
        model=generator.model,
        candidate=candidate.name,
    )
