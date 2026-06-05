# 자연휴양림 AI 에이전트 PoC 설계

작성일: 2026-06-04 KST
관련 데이터 설계: `docs/superpowers/specs/2026-06-03-foresttrip-crawler-design.md`

## 목표

현재 CLI로 수집 중인 SQLite 데이터를 기반으로, 자연어 질문에 대해 AI 에이전트가 얼마나 정확하고 근거 있게 답변할 수 있는지 검증한다. 이 단계의 목적은 사용자 서비스 웹을 만드는 것이 아니라, 데이터 품질과 검색/응답 품질을 평가하는 PoC다.

따라서 PoC는 웹 UI보다 다음 항목에 집중한다.

- 수집 데이터가 실제 질문에 충분히 답할 수 있는지 확인
- SQL, FTS, embedding/vector search를 조합한 검색 전략 검증
- AI 에이전트가 가격/인원/지역 같은 정량 조건을 정확히 처리하는지 확인
- 할인/혜택/물놀이/바베큐처럼 표현이 유연한 질문에 대해 근거 문서를 잘 찾는지 확인
- 답변에 출처, 근거 문구, 수집 시점을 포함하도록 검증

## 결정된 방향

| 항목 | 결정 |
| --- | --- |
| PoC 스택 | Python 단일 스택 |
| Agent SDK | OpenAI Agents SDK for Python |
| UI | PoC 단계에서는 제외. CLI `ask` 또는 간단한 FastAPI endpoint만 사용 |
| LangGraph | 초기 PoC에서는 제외. 복잡한 다단계 워크플로우가 필요해질 때 도입 검토 |
| Vercel AI SDK | PoC에서는 제외. 실제 사용자 웹을 만들 때 UI streaming/React 채팅 구현용으로 재검토 |
| 검색 방식 | SQL + SQLite FTS5 + embedding/vector search의 hybrid retrieval |
| 답변 원칙 | DB/검색 결과에 근거한 답변만 생성. 불확실하면 불확실하다고 표시 |

## 범위

### 포함

- CLI 기반 질의응답 명령 추가
- SQLite read-only query tools 구현
- FTS5 기반 키워드 검색
- embedding/vector search 인덱스 구축
- OpenAI Agents SDK 기반 에이전트 구성
- 대표 질문 세트와 응답 평가 로그 저장

### 제외

- 사용자용 웹 서비스 UI
- Next.js/Vercel AI SDK 기반 채팅 UI
- LangGraph 기반 durable workflow
- 예약 가능 여부 실시간 확인
- 외부 웹 검색 기반 최신성 보강
- 결제/로그인/사용자 계정 기능

## 전체 아키텍처

```text
사용자 질문
→ jforest ask 또는 /ask
→ OpenAI Agents SDK Agent
→ query/search tools
   → SQLite SQL 조회
   → SQLite FTS5 검색
   → vector search
→ 검색 결과 병합 및 랭킹
→ 근거 기반 답변 생성
→ 답변/근거/tool 로그 저장
```

PoC에서는 에이전트와 검색 로직을 기존 `jforest` Python 코드베이스 안에 둔다. 수집/파싱/DB 접근 코드가 이미 Python에 있으므로, TypeScript나 별도 웹 프레임워크로 옮기지 않는다.

## 검색 전략

### SQL이 담당하는 조건

정확한 필터링과 정렬이 필요한 조건은 SQL로 처리한다.

- 지역
- 휴양림 ID/이름
- 객실 ID/이름
- 기준 인원/최대 인원
- 가격, 최저가, 가격 범위
- 휴양림 유형
- 수집 시각

예: "4인 가족이 저렴하게 갈만한 곳"은 `rooms.capacity_*`, `room_prices.price`, `forests` 조인을 기준으로 계산한다.

### FTS가 담당하는 조건

명시적인 키워드가 포함된 텍스트 검색은 SQLite FTS5로 처리한다.

- 공지 제목/본문
- 객실 이용안내
- 편의시설
- 예약정책 상세 문구
- 할인 대상/정책 문구

예: "휴장 공지", "장애인 할인", "다자녀"처럼 실제 문구와 가까운 질문.

### Vector search가 담당하는 조건

표현이 유연하거나 원문과 질문의 단어가 다를 수 있는 조건은 embedding 기반 semantic search로 처리한다.

- "물놀이 하기 좋은 곳"
- "아이와 가기 좋은 곳"
- "바베큐 하기 좋은 곳"
- "계곡 근처 느낌"
- "가족 단위로 괜찮은 곳"
- "혜택이 있는 곳"

Vector search는 후보를 찾는 역할이다. 최종 답변은 SQL 결과와 구조화 데이터로 다시 검증한다.

## 임베딩 대상

원본 HTML 전체를 그대로 임베딩하지 않고, 답변 근거가 될 수 있는 정제 텍스트 단위로 나눈다.

| source_table | 대상 필드 |
| --- | --- |
| `forests` | `name`, `tags`, `summary`, `reservation_intake` |
| `room_usage_texts` | `amenities`, `usage_guide`, `checkin_time`, `checkout_time` |
| `discount_policies` | `target`, `category`, `timing`, `room_rates`, `campsite_rate`, `facility_rate` |
| `reservation_policies` | `fcfs_method`, `lottery_types`, `priority_types`, `fcfs_detail`, `lottery_detail` |
| `notices` | `title`, `content_text`, `body_text` |
| `notice_attachments` | `file_name`, `extracted_text`, `extraction_method` |
| `notice_facts` | `facts_json`, `needs_review`, `model` |

각 embedding chunk에는 다음 metadata를 저장한다.

```text
doc_id
source_table
source_pk
doc_type: forest | room_usage | discount | reservation_policy | notice | notice_attachment | notice_fact
instt_id
goods_id
title_or_name
text
fetched_at
updated_at
```

## Agent tools

초기 PoC에서는 LLM에게 자유 SQL 생성을 맡기지 않고, read-only tool을 명시적으로 제공한다.

```text
search_forests(region?, keyword?, limit?)
find_rooms(instt_id?, capacity?, max_price?, sort?)
get_room_prices(goods_id)
get_room_usage(goods_id)
search_discount_policies(instt_id?, query?, target?)
get_reservation_policy(instt_id)
search_notices(query, instt_id?, limit?)
semantic_search(query, filters?, limit?)
compare_candidates(candidate_ids, criteria)
```

Tool은 모두 DB 변경을 하지 않는다. 크롤링/재파싱/인덱스 재생성은 별도 CLI 명령으로 분리한다.

## 답변 형식

에이전트 답변은 가능하면 다음 구조를 따른다.

```text
요약 답변
추천/결과 목록
근거
주의사항 또는 불확실성
데이터 기준 시점
```

예:

```text
장애인 할인 정책이 명시된 휴양림은 다음과 같습니다.

1. A 자연휴양림
   - 할인 대상: 장애인 중증
   - 객실 할인: 비수기 주중 50%
   - 근거: discount_policies.target / room_rates
   - 수집 시점: 2026-06-04T...

주의: 실제 적용 여부는 예약 시점과 현장 확인 조건에 따라 달라질 수 있습니다.
```

## 평가 질문 세트

PoC 품질 검증을 위해 대표 질문을 별도 파일로 관리한다.

```text
장애인 할인 되는 자연휴양림 알려줘
다자녀 혜택 있는 곳 있어?
4인 가족이 저렴하게 갈만한 곳 추천해줘
물놀이 하기 좋은 곳 알려줘
바베큐 가능한 객실 찾아줘
예약 방식이 선착순인 곳 알려줘
최근 공지에 휴장 관련 내용 있어?
아이랑 가기 좋은 휴양림 추천해줘
주말 가격이 싼 4인실 찾아줘
성수기와 비수기 가격 차이가 큰 곳 알려줘
```

각 질문 실행 결과는 다음 항목을 저장한다.

```text
question
answer
tools_called
retrieved_rows
retrieved_documents
evidence_snippets
fetched_at_range
latency_ms
manual_eval_notes
```

## 품질 기준

PoC 성공 여부는 모델의 말투보다 검색과 근거 정확도를 기준으로 판단한다.

- 관련 데이터를 실제로 찾았는가
- 가격/인원/지역 조건을 SQL 기준으로 정확히 처리했는가
- "물놀이", "바베큐", "아이와 가기 좋음" 같은 유연한 질문에 관련 근거를 찾았는가
- 근거가 약한 내용을 확정적으로 말하지 않는가
- 답변에 source table, source row/document, 수집 시점이 포함되는가
- 조회 결과가 없을 때 없는 내용을 지어내지 않는가

## Vector/Embedding 벤치마크

기술 선정은 3개 후보를 같은 평가 질문 세트로 비교한다. 1차 벤치마크에서는 Vector DB를 Qdrant Local로 고정하고 embedding 모델 차이를 비교한다. Vector DB와 embedding 모델을 동시에 바꾸면 성능 차이의 원인을 분리하기 어렵기 때문이다.

### 후보군

| 후보 | Vector DB | Embedding | 목적 |
| --- | --- | --- | --- |
| A | Qdrant Local | OpenAI `text-embedding-3-small` | 비용/속도/품질의 기본 기준선 |
| B | Qdrant Local | OpenAI `text-embedding-3-large` | OpenAI embedding 품질 상한선 확인 |
| C | Qdrant Local | `bge-m3` | 오픈소스 multilingual embedding의 한국어 검색력 비교 |

### 1차 평가 지표

답변 생성 전에 retrieval 자체를 먼저 평가한다.

```text
recall@5
recall@10
mrr@10
average_latency_ms
```

핵심 지표는 `recall@5`와 `recall@10`이다. 자연어 질문에 대해 상위 5~10개 검색 결과 안에 답변 근거가 들어오는지를 본다.
`embedding_cost`, `index_size_mb`, `manual_relevance_score`는 2차 분석 지표로 남긴다. 1차 구현은 후보 간 retrieval 품질과 검색 지연시간을 먼저 비교한다.

### 평가 질문 구성

Embedding 벤치마크 질문은 의미 검색 조건에 집중한다. 가격/객실 질문은 SQL ranking 문제이므로 별도 SQL 벤치마크로 분리한다.

```text
정책/혜택:
- 장애인 할인 되는 곳 알려줘
- 다자녀 혜택 있는 휴양림 있어?
- 지역주민 할인 되는 곳 알려줘

활동/시설:
- 물놀이 하기 좋은 곳 알려줘
- 바베큐 가능한 객실 찾아줘
- 아이와 가기 좋은 휴양림 추천해줘

공지/운영:
- 최근 공지에 휴장 관련 내용 있어?
- 물놀이장 운영 공지 찾아줘
- 예약 방식이 선착순인 곳 알려줘
```

각 질문에는 기대 근거를 사람이 수동으로 붙인다. 기대 근거는 특정 답변 문장이 아니라 `source_table`, `source_pk`, `instt_id`, 관련 문구 기준으로 관리한다.

### 실행 방식

벤치마크는 에이전트 답변을 생성하지 않고 검색 결과만 비교한다.

```text
jforest bench embeddings --candidate openai-small
jforest bench embeddings --candidate openai-large
jforest bench embeddings --candidate bge-m3
jforest bench report
```

각 실행은 다음 산출물을 남긴다.

```text
tests/fixtures/bench/
  questions.jsonl
data/bench/
  runs/
    openai-small.jsonl
    openai-large.jsonl
    bge-m3.jsonl
  reports/
    embedding-benchmark.md
```

### 판정 기준

기본 선택은 다음 규칙으로 정한다.

1. `text-embedding-3-small`이 `recall@10`에서 충분하면 A를 채택한다.
2. `text-embedding-3-large`가 명확히 더 좋고 비용 차이가 감당 가능하면 B를 채택한다.
3. `bge-m3`가 한국어/시설 표현에서 더 좋은 recall을 보이고 로컬 추론 비용이 감당 가능하면 C를 채택한다.

Vector DB는 1차에서 Qdrant Local을 유지한다. 1차 후보 중 embedding을 결정한 뒤, 운영 단순성이 더 중요해지면 2차로 `Qdrant Local`과 `sqlite-vec`를 같은 embedding 모델로 비교한다.

## 후속 확장

PoC에서 질의응답 품질이 충분하면 다음 단계로 확장한다.

1. FastAPI endpoint 추가
2. 간단한 내부 테스트 UI 추가
3. 사용자 서비스 웹 별도 설계
4. Next.js/Vercel AI SDK 기반 스트리밍 UI 검토
5. 복잡한 다단계 추천 흐름이 필요할 경우 LangGraph 검토

## RAG Chatbot PoC Path

- Default retriever: Qdrant Local collection at `data/qdrant/openai-large/jforest`.
- Default embedding model: `text-embedding-3-large`.
- Default chat model: `gpt-4.1-mini`.
- Query flow: user question -> OpenAI embedding -> Qdrant top-k search -> `forests` name rehydration -> evidence-bound prompt -> OpenAI answer.
- CLI: `uv run jforest --db data/jforest.db agent ask "<question>"`.
- Web UI: `uv run jforest --db data/jforest.db agent serve` launches a FastAPI server (`jforest/api.py`) with a `POST /ask` JSON endpoint and a single-page HTML/JS chat at `GET /`. Request-response (no streaming yet); the chat page renders the answer plus an evidence list with휴양림 names.
- Answer rule: the assistant must answer only from retrieved evidence and explicitly say when evidence is insufficient.
- Forest name rehydration: retrieved payloads carry only an opaque `instt_id`, so `agent ask` joins `instt_id -> forests.name` from SQLite (`--db`) and adds the휴양림 name to each evidence line. This lets discount/policy answers name the actual forest instead of only the discount terms.

## Known Limits

- The benchmark question set currently has 9 questions, so quality conclusions are directional.
- Qdrant Local emits a warning above 20,000 points; production should use Qdrant Docker/Cloud or a pgvector deployment.
- `bge-m3` full benchmark has not completed on local CPU.
- Retrieval currently uses raw top-k vector search without reranking or deduplication.
- Empty or weak retrieval is handled by prompt policy and an explicit "검색된 근거가 없습니다." evidence block, but still needs live answer review.
- Generated answers still need human review for hallucination, stale notice interpretation, and policy nuance.
