# RAG Chatbot PoC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a minimal RAG chatbot path that answers flexible Korean questions from the indexed jforest corpus with cited evidence.

**Architecture:** Reuse the fixed embedding corpus, `openai-large` Qdrant local index, and OpenAI chat generation. Keep the first PoC as a Python backend/CLI capability so the team can measure answer quality before investing in a production web UI.

**Tech Stack:** Python, Click, OpenAI SDK, Qdrant Local, SQLite, pytest.

---

## File Structure

- Create `jforest/rag.py`: query embedding, vector search, context packing, prompt construction, OpenAI answer generation, and a small result dataclass.
- Modify `jforest/cli.py`: add `agent ask` command that calls `answer_question`.
- Create `tests/test_rag.py`: unit tests for context formatting, prompt constraints, fake embedder/generator answer flow.
- Create `tests/test_cli_agent.py`: CLI smoke test for the new `agent` group.
- Modify `docs/superpowers/specs/2026-06-04-ai-agent-poc-design.md`: append the implemented PoC path and current embedding recommendation.

## Decisions

- Default embedding candidate: `openai-large`, because the fixed-corpus benchmark scored `recall@10=1.000` and `mrr@10=0.944`.
- Retrieval default: top 8 documents. This is enough for flexible questions while keeping prompt size controlled.
- Answer policy: answer only from retrieved evidence. If evidence is weak, say the data is insufficient and list what was found.
- Citation format: include source table, source primary key, title/name, and score in a compact evidence block.
- UI for this phase: CLI first. A web chat UI can be added after answer quality is acceptable.
- Data source for answers: `agent ask` initializes SQLite through the existing global CLI setup, but the RAG answer path uses Qdrant payloads only. Full source rehydration from SQLite is intentionally out of scope for this PoC.
- JSON output: `agent ask --json` emits one compact JSON object per invocation so smoke results can be saved as JSONL.

---

### Task 1: Add RAG Unit Core

**Files:**
- Create: `jforest/rag.py`
- Test: `tests/test_rag.py`

- [ ] **Step 1: Write failing tests for evidence formatting and prompt rules**

Create `tests/test_rag.py`:

```python
from jforest.rag import RetrievedDocument, build_messages, format_evidence


def test_format_evidence_includes_source_identity_and_text():
    docs = [
        RetrievedDocument(
            doc_id="discount:1",
            source_table="discount_policies",
            source_pk="1",
            doc_type="discount",
            title_or_name="장애인",
            text="장애인 대상 객실 할인 50%",
            score=0.91,
            instt_id="F001",
            goods_id=None,
        )
    ]

    evidence = format_evidence(docs)

    assert "[1]" in evidence
    assert "discount_policies:1" in evidence
    assert "장애인 대상 객실 할인 50%" in evidence
    assert "score=0.910" in evidence


def test_build_messages_requires_evidence_bound_answer():
    messages = build_messages(
        question="장애인 할인 되는 곳 알려줘",
        evidence="discount_policies:1\n장애인 대상 객실 할인 50%",
    )

    assert messages[0]["role"] == "system"
    assert "검색된 근거" in messages[0]["content"]
    assert "충분하지 않으면" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "장애인 할인 되는 곳 알려줘" in messages[1]["content"]


def test_empty_evidence_is_explicit():
    evidence = format_evidence([])
    messages = build_messages("없는 조건 알려줘", evidence)

    assert evidence == "검색된 근거가 없습니다."
    assert "검색된 근거가 없습니다." in messages[1]["content"]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest tests/test_rag.py -q
```

Expected: FAIL because `jforest.rag` does not exist.

- [ ] **Step 3: Implement the minimal RAG formatting core**

Create `jforest/rag.py`:

```python
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
```

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
uv run pytest tests/test_rag.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jforest/rag.py tests/test_rag.py
git commit -m "feat: add rag evidence formatting"
```

---

### Task 2: Add Retrieval and Answer Generation

**Files:**
- Modify: `jforest/rag.py`
- Test: `tests/test_rag.py`

- [ ] **Step 1: Add failing test for injected embedder/index/generator flow**

Append to `tests/test_rag.py`:

```python
from jforest.embeddings import EmbeddingCandidate
from jforest.rag import answer_question


class FakeEmbedder:
    candidate = EmbeddingCandidate("fake", 3, "test", "fake-model")

    def embed_texts(self, texts):
        assert texts == ["바베큐 하기 좋은 곳"]
        return [[0.1, 0.2, 0.3]]


class FakeIndex:
    def search(self, vector, limit):
        assert vector == [0.1, 0.2, 0.3]
        assert limit == 8
        return [
            {
                "doc_id": "room_usage:R1",
                "source_table": "room_usage_texts",
                "source_pk": "R1",
                "doc_type": "room_usage",
                "title_or_name": "숲속의집",
                "text": "바베큐 시설 이용 가능",
                "score": 0.88,
                "instt_id": "F001",
                "goods_id": "R1",
            }
        ]


class FakeGenerator:
    model = "fake-chat"

    def generate(self, messages):
        assert "바베큐 하기 좋은 곳" in messages[1]["content"]
        assert "바베큐 시설 이용 가능" in messages[1]["content"]
        return "숲속의집은 바베큐 시설 이용 가능 근거가 있습니다. [1]"


def test_answer_question_uses_retrieval_and_generation():
    result = answer_question(
        "바베큐 하기 좋은 곳",
        embedder=FakeEmbedder(),
        index=FakeIndex(),
        generator=FakeGenerator(),
    )

    assert result.answer == "숲속의집은 바베큐 시설 이용 가능 근거가 있습니다. [1]"
    assert result.candidate == "fake"
    assert result.model == "fake-chat"
    assert result.evidence[0].source_table == "room_usage_texts"
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
uv run pytest tests/test_rag.py::test_answer_question_uses_retrieval_and_generation -q
```

Expected: FAIL because `answer_question` is not implemented.

- [ ] **Step 3: Implement retrieval/generation interfaces**

Modify `jforest/rag.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
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


def answer_question(
    question: str,
    *,
    candidate_name: str = "openai-large",
    qdrant_root: str = "data/qdrant",
    collection: str = "jforest",
    limit: int = 8,
    chat_model: str = "gpt-4.1-mini",
    embedder: Embedder | None = None,
    index: VectorSearch | None = None,
    generator: AnswerGenerator | None = None,
) -> RagAnswer:
    embedder = embedder or get_embedder(candidate_name)
    candidate = embedder.candidate
    index = index or QdrantLocalIndex(
        root=f"{qdrant_root}/{candidate.name}",
        collection=collection,
        dimension=candidate.dimension,
    )
    generator = generator or OpenAIAnswerGenerator(model=chat_model)

    vector = embedder.embed_texts([question])[0]
    payloads = index.search(vector, limit=limit)
    docs = [_doc_from_payload(payload) for payload in payloads]
    messages = build_messages(question, format_evidence(docs))
    answer = generator.generate(messages)
    return RagAnswer(
        question=question,
        answer=answer,
        evidence=docs,
        model=generator.model,
        candidate=candidate.name,
    )
```

- [ ] **Step 4: Run RAG tests**

Run:

```bash
uv run pytest tests/test_rag.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jforest/rag.py tests/test_rag.py
git commit -m "feat: generate rag answers from retrieved evidence"
```

---

### Task 3: Add Agent CLI

**Files:**
- Modify: `jforest/cli.py`
- Test: `tests/test_cli_agent.py`

- [ ] **Step 1: Add failing CLI help test**

Create `tests/test_cli_agent.py`:

```python
from click.testing import CliRunner

from jforest.cli import main


def test_agent_group_exposes_ask_command(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["--db", str(tmp_path / "x.db"), "agent", "--help"])

    assert result.exit_code == 0
    assert "ask" in result.output
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
uv run pytest tests/test_cli_agent.py -q
```

Expected: FAIL because `agent` command does not exist.

- [ ] **Step 3: Add `agent ask` command**

Modify `jforest/cli.py` by adding this group before `status`:

```python
@main.group()
def agent():
    """AI 에이전트 PoC."""


@agent.command("ask")
@click.argument("question")
@click.option("--candidate", default="openai-large", type=click.Choice(sorted(CANDIDATES)))
@click.option("--qdrant-root", default="data/qdrant")
@click.option("--model", "chat_model", default="gpt-4.1-mini")
@click.option("--limit", "retrieval_limit", default=8, type=int)
@click.option("--json", "as_json", is_flag=True)
def agent_ask(question, candidate, qdrant_root, chat_model, retrieval_limit, as_json):
    """색인된 데이터 근거로 질문에 답한다."""
    import json
    from dataclasses import asdict

    from jforest.rag import answer_question

    result = answer_question(
        question,
        candidate_name=candidate,
        qdrant_root=qdrant_root,
        chat_model=chat_model,
        limit=retrieval_limit,
    )
    if as_json:
        click.echo(json.dumps(asdict(result), ensure_ascii=False))
        return

    click.echo(result.answer)
    click.echo("")
    click.echo("근거:")
    for index, doc in enumerate(result.evidence, start=1):
        click.echo(
            f"[{index}] {doc.source_table}:{doc.source_pk} "
            f"{doc.title_or_name or doc.doc_type} score={doc.score:.3f}"
        )
```

- [ ] **Step 4: Run CLI test**

Run:

```bash
uv run pytest tests/test_cli_agent.py -q
```

Expected: PASS.

- [ ] **Step 5: Run full tests**

Run:

```bash
uv run pytest -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add jforest/cli.py tests/test_cli_agent.py
git commit -m "feat: add rag agent cli"
```

---

### Task 4: Manual PoC Validation

**Files:**
- Runtime output: `data/bench/runs/agent-smoke.jsonl`

- [ ] **Step 1: Confirm index exists**

Run:

```bash
test -d data/qdrant/openai-large && echo "openai-large index exists"
```

Expected:

```text
openai-large index exists
```

- [ ] **Step 2: Run five representative questions**

Run:

```bash
uv run jforest --db data/jforest.db agent ask "장애인 할인이 되는 휴양림 알려줘" --json
uv run jforest --db data/jforest.db agent ask "다자녀 혜택이 있는 곳 알려줘" --json
uv run jforest --db data/jforest.db agent ask "물놀이 하기 좋은 곳 추천해줘" --json
uv run jforest --db data/jforest.db agent ask "바베큐 하기 좋은 숙소가 있어?" --json
uv run jforest --db data/jforest.db agent ask "가격이 저렴한 곳을 찾고 있어" --json
```

Expected: each response contains non-empty `answer`, `evidence`, `candidate=openai-large`, and `model=gpt-4.1-mini`.

- [ ] **Step 3: Save smoke results**

Run:

```bash
mkdir -p data/bench/runs
{
  uv run jforest --db data/jforest.db agent ask "장애인 할인이 되는 휴양림 알려줘" --json
  uv run jforest --db data/jforest.db agent ask "다자녀 혜택이 있는 곳 알려줘" --json
  uv run jforest --db data/jforest.db agent ask "물놀이 하기 좋은 곳 추천해줘" --json
  uv run jforest --db data/jforest.db agent ask "바베큐 하기 좋은 숙소가 있어?" --json
  uv run jforest --db data/jforest.db agent ask "가격이 저렴한 곳을 찾고 있어" --json
} > data/bench/runs/agent-smoke.jsonl
```

Expected: `data/bench/runs/agent-smoke.jsonl` exists and contains five JSONL lines.

Because `agent ask --json` emits compact single-line JSON, the file is valid JSONL: one object per line.

- [ ] **Step 4: Commit**

```bash
git add data/bench/runs/agent-smoke.jsonl
git commit -m "test: capture rag agent smoke results"
```

If `data/` is intentionally ignored, skip this commit and report the smoke file path only.

---

### Task 5: Document Current PoC State

**Files:**
- Modify: `docs/superpowers/specs/2026-06-04-ai-agent-poc-design.md`

- [ ] **Step 1: Append implementation notes**

Append this section:

```markdown
## RAG Chatbot PoC Path

- Default retriever: Qdrant Local collection at `data/qdrant/openai-large/jforest`.
- Default embedding model: `text-embedding-3-large`.
- Default chat model: `gpt-4.1-mini`.
- Query flow: user question -> OpenAI embedding -> Qdrant top-k search -> evidence-bound prompt -> OpenAI answer.
- Current UI: CLI via `uv run jforest --db data/jforest.db agent ask "<question>"`.
- Answer rule: the assistant must answer only from retrieved evidence and explicitly say when evidence is insufficient.
- `agent ask` accepts `--db` because it shares the existing Click root command, but the current answer path reads Qdrant payload text only.

## Known Limits

- The benchmark question set currently has 9 questions, so quality conclusions are directional.
- Qdrant Local emits a warning above 20,000 points; production should use Qdrant Docker/Cloud or a pgvector deployment.
- `bge-m3` full benchmark has not completed on local CPU.
- Retrieval currently uses raw top-k vector search without reranking or deduplication.
- Empty or weak retrieval is handled by prompt policy and an explicit "검색된 근거가 없습니다." evidence block, but still needs live answer review.
- Generated answers still need human review for hallucination, stale notice interpretation, and policy nuance.
```

- [ ] **Step 2: Run docs-neutral test suite**

Run:

```bash
uv run pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-06-04-ai-agent-poc-design.md
git commit -m "docs: record rag chatbot poc path"
```

---

## Final Verification

- [ ] Run full tests:

```bash
uv run pytest -q
```

Expected: all tests pass.

- [ ] Run one live answer:

```bash
set -a; source .env; set +a
uv run jforest --db data/jforest.db agent ask "장애인 할인이 되는 휴양림 알려줘"
```

Expected: answer text plus evidence list.

- [ ] Confirm the configured chat model is available to the current OpenAI account:

```bash
set -a; source .env; set +a
uv run python - <<'PY'
from openai import OpenAI

client = OpenAI()
client.models.retrieve("gpt-4.1-mini")
print("gpt-4.1-mini available")
PY
```

Expected:

```text
gpt-4.1-mini available
```

- [ ] Confirm no long-running benchmark jobs remain:

```bash
ps -Ao pid,ppid,pcpu,pmem,etime,command | rg "jforest --db data/jforest.db (bench|agent|structure)" | rg -v "rg" || true
```

Expected: no output.

## Self-Review

- Spec coverage: The plan covers retrieval, answer generation, CLI usage, evidence display, and PoC validation.
- Placeholder scan: No `TBD`, `TODO`, or unspecified implementation steps remain.
- Type consistency: `RetrievedDocument`, `RagAnswer`, `answer_question`, `format_evidence`, and `build_messages` use the same names across tests, implementation, and CLI.
