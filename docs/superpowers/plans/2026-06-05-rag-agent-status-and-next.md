# RAG 에이전트 — 작업 현황 & 다음 작업 (핸드오프)

> 작성 2026-06-05. PoC(검색·생성·웹UI·평가·개선)까지 완료된 상태의 스냅샷.
> 관련 문서: `docs/superpowers/specs/2026-06-04-ai-agent-poc-design.md`(설계+측정 기록),
> `docs/superpowers/plans/2026-06-04-rag-chatbot-poc.md`(최초 PoC 계획).

---

## 1. 한눈에 보기

국립자연휴양림 코퍼스(공지·할인·객실·예약정책 등)를 임베딩 검색 + OpenAI 생성으로 답하는
RAG 에이전트. **CLI + 웹 채팅 UI + 평가 하니스**까지 구현됐고, 답변 품질 개선은
**eval-first(측정→개선→재측정)** 방식으로 enrichment·리랭커까지 적용·검증 완료.

- 테스트: **117 passed**
- 라이브 인덱스: `data/qdrant/openai-large` = **enriched(승격됨)**, 롤백본 `…openai-large.baseline-bak`
- 측정된 검색 품질(forest 골든셋): recall@10 **0.091 → 0.818(enrich) → 1.000(+rerank)**

---

## 2. 완료된 작업 (이번 세션 커밋)

| 커밋 | 내용 |
| --- | --- |
| `8d7b757` | RAG 근거 포맷팅 코어 (`format_evidence`, `build_messages`) |
| `af60e14` | 검색+생성 (`answer_question`, DI 구조) |
| `f59db04` | CLI `agent ask` |
| `f51d740` | PoC 경로 문서화 |
| `79440ad` | **휴양림명 rehydration** (답변측: `instt_id → forests.name` join) |
| `e0edbba` | **FastAPI 웹 채팅 UI** (`agent serve`, `POST /ask` + `GET /`) |
| `d59b0f5` | **LLM-judge 답변 평가 하니스** (`agent eval`, faithfulness/relevance) |
| `fd73334` | **임베딩 enrichment** (검색측: 필드덤프 문서에 `휴양림: 이름 (지역)` 주입) |
| `da84b10` | **forest 검색 골든셋** + enrichment 측정 |
| `4f5a029` | enriched 인덱스 **라이브 승격** |
| `24bb133` | **opt-in cross-encoder 리랭커** (`--rerank`) |

### 핵심 모듈
- `jforest/rag.py` — 검색·생성 파이프라인. `answer_question(...)` 진입점. DI: `embedder/index/generator/name_resolver/reranker` 모두 주입 가능 → 오프라인 테스트. `BgeReranker`, `SqliteForestNames` 포함.
- `jforest/ai_docs.py` — 임베딩 코퍼스 생성. `build_embedding_documents`, `region_from_arcd`, `ENRICHED_DOC_TYPES`(discount/reservation_policy/room_usage).
- `jforest/answer_eval.py` — LLM-judge 평가. `run_answer_eval`, `OpenAIJudge`(주입형), `summarize_answer_eval`.
- `jforest/api.py` — FastAPI. `create_app(answer_fn=...)` 팩토리(테스트용 주입).
- `jforest/cli.py` — `agent ask/serve/eval` (`--rerank`, `--json` 등).

### 골든셋(fixtures)
- `tests/fixtures/bench/questions.jsonl` — 검색 recall/mrr용 9문항(쉬움, 기존).
- `tests/fixtures/bench/answer-eval-cases.jsonl` — 답변평가 12문항(adversarial).
- `tests/fixtures/bench/retrieval-forest-cases.jsonl` — 휴양림-특정/지역 11문항(DB 도출 정답).

### 사용법
```bash
set -a; source .env; set +a          # OPENAI_API_KEY 필요
uv run jforest --db data/jforest.db agent ask "장애인 할인 되는 휴양림" [--rerank] [--json]
uv run jforest --db data/jforest.db agent serve     # http://127.0.0.1:8000 웹 채팅
uv run jforest --db data/jforest.db agent eval --cases tests/fixtures/bench/answer-eval-cases.jsonl [--rerank]
```

---

## 3. 측정으로 입증한 개선 (forest 검색 골든셋)

| 단계 | recall@10 | mrr@10 |
| --- | ---: | ---: |
| baseline | 0.091 | 0.045 |
| + enrichment | 0.818 | 0.619 |
| + 리랭커(pool=50) | **1.000** | **0.894** |

답변평가(LLM-judge): 쉬운셋 faith 1.000/rel 0.978, adversarial faith 0.983/rel 0.975.

---

## 4. eval-first가 막은 잘못된 결론 (재현 주의)

1. **naive enrichment**(전체 문서 주입) → 답변 faithfulness 회귀(0.992→0.979). 하니스가 포착 → **필드덤프 한정**으로 수정해 해결.
2. **리랭커 pool=30** → 첫 probe가 "효과 없음" 오판(묻힌 문서가 풀 밖). pool=50 측정으로 실제 큰 효과 확인.
3. **BM25 필요성 probe** → 첫 측정이 정답을 좁게/잘리게 잡아 false miss 3/5. 완전 정답으로 재측정하니 **0/5 실패**.

→ 교훈: **golden-set 정답 완전성**과 **후보 풀 크기**가 측정 신뢰도를 좌우. 측정 전에 의심하라.

---

## 5. 남은 작업 (증거 기반 우선순위)

### ❌ 하지 말 것 — 증거상 불필요
- **하이브리드 BM25 / sparse 검색**: BM25 강점 패턴(정확 고유명사·영문↔한글·오타·약어)을 완전 정답으로 측정 시 dense(text-embedding-3-large)가 **5/5 통과**. 메울 갭 없음.
- **무작정 검색/생성 최적화**: 두 측정자(검색 1.000, 답변 ~1.0)가 **포화** → 효과 입증 불가.

### ✅ 정당한 후보
1. **답변-품질 골든셋 확대 (30~50문항)** — *유일하게 증거 기반으로 정당한 검색계열 작업.*
   현재 측정자가 포화/노이즈라, 미지의 실패를 *발굴*해야 다음 작업 근거가 생김. 실패가 거의 없으면 PoC 종료 근거가 되고, 보이면 그게 타깃.
2. **데이터 구조화 / 품질** — *진짜 남은 병목 후보.*
   칠갑산 bbq 사례: 검색은 고쳐졌지만 `room_usage` 원문이 **객실별 바베큐 가능 여부를 명확히 표기 안 함** → 답변이 "불명확". 검색/랭킹이 아니라 소스 데이터 문제. `notice_facts`처럼 객실 시설을 구조화하면 답변 정확도 향상 여지.
3. **PoC 종료 선언** — 원래 목표("웹 투자 전 답변 품질 측정") 달성. 검색/생성은 충분히 좋음. 지연(리랭커 latency)·배포·인증 등 다른 축으로 이동.

### 🔧 운영/기술 부채
- 리랭커 CPU 지연 2~5초/쿼리 + 매 CLI 호출 ~8초 모델 로드 → opt-in. 프로덕션은 **영속 서버(1회 로드)/GPU/Cohere Rerank** 필요.
- `agent eval`의 `insufficient_rate`는 빈-evidence 기준이라 "답불가 인식"을 직접 못 잼(검색이 늘 k건 반환). **텍스트 기반 "올바르게 거절" 지표** 추가 여지.
- 답변평가 golden set 12문항은 통계적으로 작음 + judge 노이즈.
- 스트리밍 미구현(현재 request-response). spec 4단계(Next.js/SSE)는 후순위.
- `data/qdrant/openai-large.baseline-bak`(705M) 롤백 불필요 확정되면 삭제 가능.

---

## 6. 재현/환경 메모
- `OPENAI_API_KEY`는 `.env`(gitignore). 임베딩=text-embedding-3-large, 생성/judge=gpt-4.1-mini.
- Qdrant Local 24,647 points(>20k 경고 정상). 프로덕션은 Qdrant Docker/Cloud or pgvector.
- 인덱스 재생성: `uv run jforest --db data/jforest.db bench embeddings --candidate openai-large --reindex` (코퍼스가 enriched이므로 자동 enriched 색인).
- `data/`는 gitignore → 인덱스/run 결과 미커밋.
