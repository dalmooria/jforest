from __future__ import annotations

import json
import time
from pathlib import Path

from jforest.ai_docs import build_embedding_documents, load_embedding_documents, save_embedding_documents
from jforest.embeddings import CANDIDATES, get_embedder
from jforest.vector_index import QdrantLocalIndex


def expected_hit_rank(expected: list[dict], results: list[dict], k: int) -> int | None:
    expected_keys = {
        (item.get("source_table"), item.get("source_pk"))
        for item in expected
        if item.get("source_table") and item.get("source_pk")
    }
    for index, result in enumerate(results[:k], start=1):
        key = (result.get("source_table"), result.get("source_pk"))
        if key in expected_keys:
            return index
    return None


def recall_at_k(hit_rank: int | None, k: int) -> float:
    return 1.0 if hit_rank is not None and hit_rank <= k else 0.0


def mrr_at_k(hit_rank: int | None, k: int) -> float:
    if hit_rank is None or hit_rank > k:
        return 0.0
    return 1.0 / hit_rank


def load_questions(path: str) -> list[dict]:
    questions = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                questions.append(json.loads(line))
    return questions


def snapshot_corpus(conn, output_path: str) -> int:
    docs = build_embedding_documents(conn)
    save_embedding_documents(docs, output_path)
    return len(docs)


def _get_documents(conn, corpus_path: str | None):
    if corpus_path:
        return load_embedding_documents(corpus_path)
    return build_embedding_documents(conn)


def index_candidate(
    conn,
    candidate_name: str,
    qdrant_root: str,
    batch_size: int = 64,
    corpus_path: str | None = None,
    progress=None,
) -> int:
    candidate = CANDIDATES[candidate_name]
    embedder = get_embedder(candidate_name)
    docs = _get_documents(conn, corpus_path)
    index = QdrantLocalIndex(
        root=f"{qdrant_root}/{candidate_name}",
        collection="jforest",
        dimension=candidate.dimension,
    )
    index.recreate()
    total = len(docs)
    for start in range(0, total, batch_size):
        batch = docs[start : start + batch_size]
        vectors = embedder.embed_texts([doc.text for doc in batch])
        index.upsert(batch, vectors)
        if progress:
            progress(min(start + len(batch), total), total)
    return len(docs)


def run_candidate(
    conn,
    candidate_name: str,
    questions_path: str,
    qdrant_root: str,
    output_path: str,
    limit: int = 10,
    corpus_path: str | None = None,
) -> None:
    candidate = CANDIDATES[candidate_name]
    embedder = get_embedder(candidate_name)
    index = QdrantLocalIndex(
        root=f"{qdrant_root}/{candidate_name}",
        collection="jforest",
        dimension=candidate.dimension,
    )
    questions = load_questions(questions_path)
    corpus_docs = len(_get_documents(conn, corpus_path))
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for question in questions:
            started = time.perf_counter()
            query_vector = embedder.embed_texts([question["question"]])[0]
            results = index.search(query_vector, limit=limit)
            latency_ms = int((time.perf_counter() - started) * 1000)
            hit_rank_5 = expected_hit_rank(question.get("expected", []), results, k=5)
            hit_rank_10 = expected_hit_rank(question.get("expected", []), results, k=10)
            record = {
                "candidate": candidate_name,
                "question_id": question["id"],
                "question": question["question"],
                "category": question.get("category"),
                "corpus_path": corpus_path,
                "corpus_docs": corpus_docs,
                "latency_ms": latency_ms,
                "recall_at_5": recall_at_k(hit_rank_5, 5),
                "recall_at_10": recall_at_k(hit_rank_10, 10),
                "mrr_at_10": mrr_at_k(hit_rank_10, 10),
                "results": results,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def summarize_run(path: str) -> dict:
    rows = load_questions(path)
    if not rows:
        return {
            "count": 0,
            "recall_at_5": 0.0,
            "recall_at_10": 0.0,
            "mrr_at_10": 0.0,
            "average_latency_ms": 0.0,
        }
    return {
        "count": len(rows),
        "recall_at_5": sum(row["recall_at_5"] for row in rows) / len(rows),
        "recall_at_10": sum(row["recall_at_10"] for row in rows) / len(rows),
        "mrr_at_10": sum(row["mrr_at_10"] for row in rows) / len(rows),
        "average_latency_ms": sum(row["latency_ms"] for row in rows) / len(rows),
    }


def write_report(runs_dir: str, output_path: str) -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Embedding Benchmark Report",
        "",
        "| candidate | n | recall@5 | recall@10 | mrr@10 | avg latency ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for candidate in sorted(CANDIDATES):
        path = f"{runs_dir}/{candidate}.jsonl"
        if not Path(path).exists():
            lines.append(f"| {candidate} | 0 | n/a | n/a | n/a | n/a |")
            continue
        summary = summarize_run(path)
        lines.append(
            f"| {candidate} | {summary['count']} | "
            f"{summary['recall_at_5']:.3f} | {summary['recall_at_10']:.3f} | "
            f"{summary['mrr_at_10']:.3f} | {summary['average_latency_ms']:.1f} |"
        )
    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
