# AI Agent Embedding Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a PoC benchmark CLI that compares three embedding candidates for natural-language retrieval over the collected foresttrip SQLite data.

**Architecture:** Keep the benchmark inside the existing Python CLI project. SQLite remains the source of truth for structured data and benchmark metadata; Qdrant Local stores vectors for each candidate; the benchmark evaluates retrieval quality before any AI answer generation.

**Tech Stack:** Python 3.11, Click, SQLite, pytest, qdrant-client local mode, OpenAI embeddings, sentence-transformers for `bge-m3`.

---

## File Structure

- Create: `jforest/ai_docs.py`
  - Builds normalized retrieval documents from current SQLite tables.
  - Does not call embedding providers or vector DB.
- Create: `jforest/embeddings.py`
  - Defines embedding provider interface and three providers: `openai-small`, `openai-large`, `bge-m3`.
- Create: `jforest/vector_index.py`
  - Owns Qdrant Local collection creation, upsert, and search.
- Create: `jforest/bench.py`
  - Loads benchmark questions, runs candidate searches, computes metrics, and writes reports.
- Modify: `jforest/cli.py`
  - Adds `bench embeddings` and `bench report` commands.
- Create: `tests/test_ai_docs.py`
  - Unit tests for retrieval document extraction.
- Create: `tests/test_bench_metrics.py`
  - Unit tests for recall/MRR calculations.
- Create: `tests/test_cli_bench.py`
  - CLI smoke tests for the benchmark command group.
- Create: `tests/fixtures/bench/questions.jsonl`
  - Manual benchmark questions and expected evidence.

Runtime-generated paths:

- `data/qdrant/<candidate>/`
- `data/bench/runs/<candidate>.jsonl`
- `data/bench/reports/embedding-benchmark.md`

## Task 1: Add Benchmark Data Types And Document Builder

**Files:**
- Create: `jforest/ai_docs.py`
- Test: `tests/test_ai_docs.py`

- [ ] **Step 1: Write failing tests for retrieval document extraction**

Create `tests/test_ai_docs.py`:

```python
import sqlite3

from jforest.ai_docs import build_embedding_documents
from jforest.db import init_db


def test_build_embedding_documents_includes_room_usage_and_notice():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    conn.execute(
        "INSERT INTO forests (instt_id, name, tags, summary, reservation_intake, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("F1", "가리산자연휴양림", '["계곡"]', "계곡과 산책로가 있다", "선착순", "2026-06-04T00:00:00"),
    )
    conn.execute(
        "INSERT INTO rooms (goods_id, instt_id, name, fetched_at) VALUES (?, ?, ?, ?)",
        ("G1", "F1", "숲속의집 101호", "2026-06-04T00:00:00"),
    )
    conn.execute(
        "INSERT INTO room_usage_texts (goods_id, amenities, usage_guide, fetched_at) VALUES (?, ?, ?, ?)",
        ("G1", "바베큐장, 계곡", "여름철 물놀이 가능", "2026-06-04T00:00:00"),
    )
    conn.execute(
        "INSERT INTO notices (instt_id, twbbs_id, title, body_text, content_text, updated_at, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "F1",
            "N1",
            "물놀이장 운영 안내",
            "본문 전체",
            "7월부터 물놀이장을 운영합니다.",
            "2026-06-01",
            "2026-06-04T00:00:00",
        ),
    )
    conn.execute(
        "INSERT INTO notice_attachments "
        "(instt_id, twbbs_id, file_master_id, file_id, file_name, extracted_text, extraction_method, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("F1", "N1", "FM1", "FILE1", "물놀이장 안내문.pdf", "어린이 물놀이장 이용시간 안내", "pdftext", "2026-06-04T00:00:00"),
    )
    conn.execute(
        "INSERT INTO notice_facts (instt_id, twbbs_id, facts_json, model, extracted_at) VALUES (?, ?, ?, ?, ?)",
        ("F1", "N1", '{"waterPlay":"7월부터 물놀이장 운영"}', "gemini-test", "2026-06-04T00:00:00"),
    )
    conn.commit()

    docs = build_embedding_documents(conn)

    doc_ids = {doc.doc_id for doc in docs}
    assert "forest:F1" in doc_ids
    assert "room_usage:G1" in doc_ids
    assert "notice:F1:N1" in doc_ids
    assert "notice_attachment:1" in doc_ids
    assert "notice_fact:F1:N1" in doc_ids
    notice = next(doc for doc in docs if doc.doc_id == "notice:F1:N1")
    assert notice.instt_id == "F1"
    assert "7월부터 물놀이장을 운영합니다." in notice.text
    assert notice.source_table == "notices"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ai_docs.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'jforest.ai_docs'`.

- [ ] **Step 3: Implement document builder**

Create `jforest/ai_docs.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class EmbeddingDocument:
    doc_id: str
    source_table: str
    source_pk: str
    doc_type: str
    instt_id: str | None
    goods_id: str | None
    title_or_name: str | None
    text: str
    fetched_at: str | None
    updated_at: str | None = None


def _join_text(parts: Iterable[str | None]) -> str:
    return "\n".join(part.strip() for part in parts if part and part.strip())


def build_embedding_documents(conn) -> list[EmbeddingDocument]:
    docs: list[EmbeddingDocument] = []

    for row in conn.execute(
        "SELECT instt_id, name, tags, summary, reservation_intake, fetched_at FROM forests ORDER BY instt_id"
    ):
        text = _join_text([row["name"], row["tags"], row["summary"], row["reservation_intake"]])
        if text:
            docs.append(
                EmbeddingDocument(
                    doc_id=f"forest:{row['instt_id']}",
                    source_table="forests",
                    source_pk=row["instt_id"],
                    doc_type="forest",
                    instt_id=row["instt_id"],
                    goods_id=None,
                    title_or_name=row["name"],
                    text=text,
                    fetched_at=row["fetched_at"],
                )
            )

    for row in conn.execute(
        "SELECT r.goods_id, r.instt_id, r.name, u.amenities, u.usage_guide, u.checkin_time, "
        "u.checkout_time, u.fetched_at "
        "FROM room_usage_texts u JOIN rooms r ON r.goods_id = u.goods_id ORDER BY r.goods_id"
    ):
        text = _join_text([row["name"], row["amenities"], row["usage_guide"], row["checkin_time"], row["checkout_time"]])
        if text:
            docs.append(
                EmbeddingDocument(
                    doc_id=f"room_usage:{row['goods_id']}",
                    source_table="room_usage_texts",
                    source_pk=row["goods_id"],
                    doc_type="room_usage",
                    instt_id=row["instt_id"],
                    goods_id=row["goods_id"],
                    title_or_name=row["name"],
                    text=text,
                    fetched_at=row["fetched_at"],
                )
            )

    for row in conn.execute(
        "SELECT id, instt_id, target, category, timing, apply_date, room_rates, campsite_rate, "
        "facility_rate, fetched_at FROM discount_policies ORDER BY id"
    ):
        text = _join_text([
            row["target"],
            row["category"],
            row["timing"],
            row["apply_date"],
            row["room_rates"],
            row["campsite_rate"],
            row["facility_rate"],
        ])
        if text:
            docs.append(
                EmbeddingDocument(
                    doc_id=f"discount:{row['id']}",
                    source_table="discount_policies",
                    source_pk=str(row["id"]),
                    doc_type="discount",
                    instt_id=row["instt_id"],
                    goods_id=None,
                    title_or_name=row["target"],
                    text=text,
                    fetched_at=row["fetched_at"],
                )
            )

    for row in conn.execute(
        "SELECT instt_id, fcfs_method, lottery_types, priority_types, fcfs_detail, lottery_detail, fetched_at "
        "FROM reservation_policies ORDER BY instt_id"
    ):
        text = _join_text([
            row["fcfs_method"],
            row["lottery_types"],
            row["priority_types"],
            row["fcfs_detail"],
            row["lottery_detail"],
        ])
        if text:
            docs.append(
                EmbeddingDocument(
                    doc_id=f"reservation_policy:{row['instt_id']}",
                    source_table="reservation_policies",
                    source_pk=row["instt_id"],
                    doc_type="reservation_policy",
                    instt_id=row["instt_id"],
                    goods_id=None,
                    title_or_name=row["instt_id"],
                    text=text,
                    fetched_at=row["fetched_at"],
                )
            )

    for row in conn.execute(
        "SELECT instt_id, twbbs_id, title, content_text, body_text, updated_at, fetched_at "
        "FROM notices ORDER BY instt_id, twbbs_id"
    ):
        text = _join_text([row["title"], row["content_text"], row["body_text"]])
        if text:
            docs.append(
                EmbeddingDocument(
                    doc_id=f"notice:{row['instt_id']}:{row['twbbs_id']}",
                    source_table="notices",
                    source_pk=f"{row['instt_id']}:{row['twbbs_id']}",
                    doc_type="notice",
                    instt_id=row["instt_id"],
                    goods_id=None,
                    title_or_name=row["title"],
                    text=text,
                    fetched_at=row["fetched_at"],
                    updated_at=row["updated_at"],
                )
            )

    for row in conn.execute(
        "SELECT id, instt_id, twbbs_id, file_name, extracted_text, extraction_method, fetched_at "
        "FROM notice_attachments WHERE extracted_text IS NOT NULL AND length(extracted_text) > 0 "
        "ORDER BY instt_id, twbbs_id, id"
    ):
        text = _join_text([row["file_name"], row["extraction_method"], row["extracted_text"]])
        if text:
            docs.append(
                EmbeddingDocument(
                    doc_id=f"notice_attachment:{row['id']}",
                    source_table="notice_attachments",
                    source_pk=str(row["id"]),
                    doc_type="notice_attachment",
                    instt_id=row["instt_id"],
                    goods_id=None,
                    title_or_name=row["file_name"],
                    text=text,
                    fetched_at=row["fetched_at"],
                )
            )

    for row in conn.execute(
        "SELECT instt_id, twbbs_id, facts_json, model, needs_review, extracted_at FROM notice_facts "
        "WHERE facts_json IS NOT NULL AND length(facts_json) > 0 ORDER BY instt_id, twbbs_id"
    ):
        source_pk = f"{row['instt_id']}:{row['twbbs_id']}"
        text = _join_text([row["model"], row["facts_json"], f"needs_review={row['needs_review']}"])
        if text:
            docs.append(
                EmbeddingDocument(
                    doc_id=f"notice_fact:{source_pk}",
                    source_table="notice_facts",
                    source_pk=source_pk,
                    doc_type="notice_fact",
                    instt_id=row["instt_id"],
                    goods_id=None,
                    title_or_name=source_pk,
                    text=text,
                    fetched_at=row["extracted_at"],
                )
            )

    return docs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ai_docs.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jforest/ai_docs.py tests/test_ai_docs.py
git commit -m "feat: build embedding documents"
```

## Task 2: Add Benchmark Metrics

**Files:**
- Create: `jforest/bench.py`
- Test: `tests/test_bench_metrics.py`

- [ ] **Step 1: Write failing tests for metrics**

Create `tests/test_bench_metrics.py`:

```python
from jforest.bench import expected_hit_rank, mrr_at_k, recall_at_k


def test_expected_hit_rank_matches_source_table_and_pk():
    expected = [{"source_table": "notices", "source_pk": "F1:N1"}]
    results = [
        {"source_table": "forests", "source_pk": "F1"},
        {"source_table": "notices", "source_pk": "F1:N1"},
    ]

    assert expected_hit_rank(expected, results, k=10) == 2


def test_recall_and_mrr_at_k():
    assert recall_at_k(2, k=5) == 1.0
    assert recall_at_k(None, k=5) == 0.0
    assert mrr_at_k(2, k=5) == 0.5
    assert mrr_at_k(None, k=5) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_bench_metrics.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'jforest.bench'`.

- [ ] **Step 3: Implement metrics**

Create `jforest/bench.py`:

```python
from __future__ import annotations


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_bench_metrics.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jforest/bench.py tests/test_bench_metrics.py
git commit -m "feat: add retrieval benchmark metrics"
```

## Task 3: Add Embedding Providers

**Files:**
- Create: `jforest/embeddings.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add dependencies**

Modify `pyproject.toml` dependencies:

```toml
dependencies = [
    "httpx>=0.27",
    "selectolax>=0.3.21",
    "click>=8.1",
    "olefile>=0.47",
    "google-cloud-vision>=3.14.0",
    "google-genai>=2.8.0",
    "openai>=2.0.0",
    "qdrant-client>=1.15.0",
    "sentence-transformers>=3.0.0",
]
```

- [ ] **Step 2: Sync dependencies**

Run: `uv sync`

Expected: lockfile updates successfully.

- [ ] **Step 3: Create provider module**

Create `jforest/embeddings.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol


@dataclass(frozen=True)
class EmbeddingCandidate:
    name: str
    dimension: int
    provider: str
    model: str


CANDIDATES = {
    "openai-small": EmbeddingCandidate("openai-small", 1536, "openai", "text-embedding-3-small"),
    "openai-large": EmbeddingCandidate("openai-large", 3072, "openai", "text-embedding-3-large"),
    "bge-m3": EmbeddingCandidate("bge-m3", 1024, "sentence-transformers", "BAAI/bge-m3"),
}


class Embedder(Protocol):
    candidate: EmbeddingCandidate

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


class OpenAIEmbedder:
    def __init__(self, candidate: EmbeddingCandidate):
        from openai import OpenAI

        self.candidate = candidate
        self.client = OpenAI()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        response = self.client.embeddings.create(model=self.candidate.model, input=texts)
        return [item.embedding for item in response.data]


class SentenceTransformerEmbedder:
    def __init__(self, candidate: EmbeddingCandidate):
        self.candidate = candidate
        self.model = _load_sentence_transformer(candidate.model)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(texts, normalize_embeddings=True)
        return [vector.tolist() for vector in vectors]


@lru_cache(maxsize=1)
def _load_sentence_transformer(model_name: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


def get_embedder(candidate_name: str) -> Embedder:
    if candidate_name not in CANDIDATES:
        choices = ", ".join(sorted(CANDIDATES))
        raise ValueError(f"unknown embedding candidate: {candidate_name}. Choices: {choices}")
    candidate = CANDIDATES[candidate_name]
    if candidate.provider == "openai":
        return OpenAIEmbedder(candidate)
    return SentenceTransformerEmbedder(candidate)
```

- [ ] **Step 4: Verify candidate import**

Run: `uv run python -c "from jforest.embeddings import CANDIDATES; print(sorted(CANDIDATES))"`

Expected output contains `['bge-m3', 'openai-large', 'openai-small']`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock jforest/embeddings.py
git commit -m "feat: add embedding candidates"
```

## Task 4: Add Qdrant Local Vector Index

**Files:**
- Create: `jforest/vector_index.py`

- [ ] **Step 1: Create vector index module**

Create `jforest/vector_index.py`:

```python
from __future__ import annotations

import hashlib
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from jforest.ai_docs import EmbeddingDocument


def stable_point_id(doc_id: str) -> int:
    digest = hashlib.sha256(doc_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


class QdrantLocalIndex:
    def __init__(self, root: str, collection: str, dimension: int):
        Path(root).mkdir(parents=True, exist_ok=True)
        self.client = QdrantClient(path=root)
        self.collection = collection
        self.dimension = dimension

    def recreate(self) -> None:
        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=VectorParams(size=self.dimension, distance=Distance.COSINE),
        )

    def upsert(self, docs: list[EmbeddingDocument], vectors: list[list[float]]) -> None:
        points = []
        for doc, vector in zip(docs, vectors, strict=True):
            points.append(
                PointStruct(
                    id=stable_point_id(doc.doc_id),
                    vector=vector,
                    payload={
                        "doc_id": doc.doc_id,
                        "source_table": doc.source_table,
                        "source_pk": doc.source_pk,
                        "doc_type": doc.doc_type,
                        "instt_id": doc.instt_id,
                        "goods_id": doc.goods_id,
                        "title_or_name": doc.title_or_name,
                        "text": doc.text[:1200],
                        "fetched_at": doc.fetched_at,
                        "updated_at": doc.updated_at,
                    },
                )
            )
        self.client.upsert(collection_name=self.collection, points=points)

    def search(self, vector: list[float], limit: int) -> list[dict]:
        hits = self.client.query_points(
            collection_name=self.collection,
            query=vector,
            limit=limit,
            with_payload=True,
        ).points
        results = []
        for hit in hits:
            payload = dict(hit.payload or {})
            payload["score"] = hit.score
            results.append(payload)
        return results
```

- [ ] **Step 2: Verify import**

Run: `uv run python -c "from jforest.vector_index import stable_point_id; print(type(stable_point_id('notice:F1:N1')).__name__)"`

Expected output: `int`.

- [ ] **Step 3: Commit**

```bash
git add jforest/vector_index.py
git commit -m "feat: add qdrant local vector index"
```

## Task 5: Add Benchmark Question File

**Files:**
- Create: `tests/fixtures/bench/questions.jsonl`

- [ ] **Step 1: Create initial question set**

Create `tests/fixtures/bench/questions.jsonl`:

```jsonl
{"id":"discount_disabled","question":"장애인 할인 되는 자연휴양림 알려줘","category":"policy","expected":[]}
{"id":"discount_multi_child","question":"다자녀 혜택 있는 휴양림 있어?","category":"policy","expected":[]}
{"id":"discount_local_resident","question":"지역주민 할인 되는 곳 알려줘","category":"policy","expected":[]}
{"id":"activity_water","question":"물놀이 하기 좋은 곳 알려줘","category":"activity","expected":[]}
{"id":"activity_bbq","question":"바베큐 가능한 객실 찾아줘","category":"activity","expected":[]}
{"id":"activity_children","question":"아이와 가기 좋은 휴양림 추천해줘","category":"activity","expected":[]}
{"id":"notice_closure","question":"최근 공지에 휴장 관련 내용 있어?","category":"notice","expected":[]}
{"id":"notice_water","question":"물놀이장 운영 공지 찾아줘","category":"notice","expected":[]}
{"id":"reservation_fcfs","question":"예약 방식이 선착순인 곳 알려줘","category":"reservation","expected":[]}
```

Price and room-capacity questions are intentionally excluded from this embedding benchmark. They belong in a separate SQL ranking benchmark because correctness depends on structured columns such as `rooms.capacity_max` and `room_prices.price`.

- [ ] **Step 2: Fill expected evidence manually before scoring**

Run exploratory SQL/FTS and replace `expected: []` with source evidence for at least 8 questions before scoring. Example shape:

```json
{"source_table":"notices","source_pk":"F1:N1","instt_id":"F1","note":"공지 제목 또는 본문에 물놀이장 운영 근거가 있음"}
```

This task is not complete until at least 8 questions have non-empty `expected` evidence.

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/bench/questions.jsonl
git commit -m "test: add embedding benchmark questions"
```

## Task 6: Add Benchmark Runner

**Files:**
- Modify: `jforest/bench.py`

- [ ] **Step 1: Replace benchmark module with metrics plus runner code**

Replace `jforest/bench.py` with:

```python
from __future__ import annotations

import json
import time
from pathlib import Path

from jforest.ai_docs import build_embedding_documents
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


def index_candidate(conn, candidate_name: str, qdrant_root: str, batch_size: int = 64) -> int:
    candidate = CANDIDATES[candidate_name]
    embedder = get_embedder(candidate_name)
    docs = build_embedding_documents(conn)
    index = QdrantLocalIndex(
        root=f"{qdrant_root}/{candidate_name}",
        collection="jforest",
        dimension=candidate.dimension,
    )
    index.recreate()
    for start in range(0, len(docs), batch_size):
        batch = docs[start : start + batch_size]
        vectors = embedder.embed_texts([doc.text for doc in batch])
        index.upsert(batch, vectors)
    return len(docs)


def run_candidate(conn, candidate_name: str, questions_path: str, qdrant_root: str, output_path: str, limit: int = 10) -> None:
    candidate = CANDIDATES[candidate_name]
    embedder = get_embedder(candidate_name)
    index = QdrantLocalIndex(
        root=f"{qdrant_root}/{candidate_name}",
        collection="jforest",
        dimension=candidate.dimension,
    )
    questions = load_questions(questions_path)
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
        return {"count": 0, "recall_at_5": 0.0, "recall_at_10": 0.0, "mrr_at_10": 0.0, "average_latency_ms": 0.0}
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
```

- [ ] **Step 2: Run module import check**

Run: `uv run python -c "from jforest.bench import index_candidate, run_candidate, summarize_run; print('ok')"`

Expected output: `ok`.

- [ ] **Step 3: Commit**

```bash
git add jforest/bench.py
git commit -m "feat: add embedding benchmark runner"
```

## Task 7: Add CLI Commands

**Files:**
- Modify: `jforest/cli.py`
- Test: `tests/test_cli_bench.py`

- [ ] **Step 1: Write CLI smoke test**

Create `tests/test_cli_bench.py`:

```python
from click.testing import CliRunner

from jforest.cli import main


def test_bench_group_exposes_report_command(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["--db", str(tmp_path / "x.db"), "bench", "--help"])

    assert result.exit_code == 0
    assert "embeddings" in result.output
    assert "report" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_bench.py -v`

Expected: FAIL because `bench` command does not exist.

- [ ] **Step 3: Add CLI commands**

Modify `jforest/cli.py` by importing benchmark helpers:

```python
from jforest.bench import index_candidate, run_candidate, summarize_run, write_report
from jforest.embeddings import CANDIDATES
```

Add below the existing commands:

```python
@main.group()
@click.pass_context
def bench(ctx):
    """검색/임베딩 벤치마크."""


@bench.command("embeddings")
@click.option("--candidate", type=click.Choice(sorted(CANDIDATES)), required=True)
@click.option("--questions", default="tests/fixtures/bench/questions.jsonl")
@click.option("--qdrant-root", default="data/qdrant")
@click.option("--runs-dir", default="data/bench/runs")
@click.option("--reindex", is_flag=True)
@click.pass_context
def bench_embeddings(ctx, candidate, questions, qdrant_root, runs_dir, reindex):
    conn = ctx.obj["conn"]
    if reindex:
        n = index_candidate(conn, candidate, qdrant_root)
        click.echo(f"indexed {n} documents for {candidate}")
    output_path = f"{runs_dir}/{candidate}.jsonl"
    run_candidate(conn, candidate, questions, qdrant_root, output_path)
    click.echo(f"wrote {output_path}")


@bench.command("report")
@click.option("--runs-dir", default="data/bench/runs")
@click.option("--output", default="data/bench/reports/embedding-benchmark.md")
def bench_report(runs_dir, output):
    for candidate in sorted(CANDIDATES):
        path = f"{runs_dir}/{candidate}.jsonl"
        try:
            summary = summarize_run(path)
        except FileNotFoundError:
            click.echo(f"{candidate}: no run")
            continue
        click.echo(
            f"{candidate}: n={summary['count']} "
            f"recall@5={summary['recall_at_5']:.3f} "
            f"recall@10={summary['recall_at_10']:.3f} "
            f"mrr@10={summary['mrr_at_10']:.3f} "
            f"latency={summary['average_latency_ms']:.1f}ms"
        )
    write_report(runs_dir, output)
    click.echo(f"wrote {output}")
```

- [ ] **Step 4: Run CLI smoke test**

Run: `uv run pytest tests/test_cli_bench.py -v`

Expected: PASS.

- [ ] **Step 5: Run full tests**

Run: `uv run pytest -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add jforest/cli.py tests/test_cli_bench.py
git commit -m "feat: add embedding benchmark cli"
```

## Task 8: Run First Benchmark

**Files:**
- Runtime output only: `data/qdrant/**`, `data/bench/runs/**`, `data/bench/reports/**`

- [ ] **Step 1: Ensure expected evidence is populated**

Open `tests/fixtures/bench/questions.jsonl` and verify at least 8 lines have non-empty `expected` arrays.

Run:

```bash
uv run python - <<'PY'
import json
rows=[json.loads(line) for line in open('tests/fixtures/bench/questions.jsonl', encoding='utf-8') if line.strip()]
print(sum(bool(row.get('expected')) for row in rows), 'questions with expected evidence')
PY
```

Expected: `8 questions with expected evidence` or higher.

- [ ] **Step 2: Run openai-small**

Run:

```bash
uv run jforest --db data/jforest.db bench embeddings --candidate openai-small --reindex
```

Expected: prints indexed document count and writes `data/bench/runs/openai-small.jsonl`.

- [ ] **Step 3: Run openai-large**

Run:

```bash
uv run jforest --db data/jforest.db bench embeddings --candidate openai-large --reindex
```

Expected: prints indexed document count and writes `data/bench/runs/openai-large.jsonl`.

- [ ] **Step 4: Run bge-m3**

Run:

```bash
uv run jforest --db data/jforest.db bench embeddings --candidate bge-m3 --reindex
```

Expected: prints indexed document count and writes `data/bench/runs/bge-m3.jsonl`.

- [ ] **Step 5: Print report**

Run:

```bash
uv run jforest --db data/jforest.db bench report
```

Expected: one line per candidate with `recall@5`, `recall@10`, `mrr@10`, and latency.

## Self-Review

Spec coverage:

- Candidate count is exactly three: Task 3 defines `openai-small`, `openai-large`, and `bge-m3`.
- Qdrant Local is fixed for 1차 benchmark: Task 4 and Task 6 use Qdrant Local for all candidates.
- Retrieval metrics are implemented before answer generation: Task 2 and Task 6 compute recall/MRR only.
- Benchmark CLI shape matches the spec intent: Task 7 provides `jforest bench embeddings` and `jforest bench report`.
- Evaluation questions are explicitly stored outside ignored runtime data: Task 5 creates `tests/fixtures/bench/questions.jsonl`.

Known implementation constraint:

- Task 5 requires manual expected-evidence annotation before benchmark scores are meaningful. Empty `expected` arrays make recall and MRR report as zero even when search results look relevant.
