# 숲나들e 자연휴양림 크롤러/수집기 설계

작성일: 2026-06-03 KST
관련 탐색 문서: `docs/foresttrip-exploration.md`, `docs/foresttrip-notice-ocr-exploration.md`

## 목표

숲나들e(foresttrip.go.kr)에서 전국 자연휴양림의 기본정보, 객실/가격, 할인/예약정책, 공지사항을 자동 수집해 SQLite DB에 적재한다. 이 데이터는 이후 자연휴양림 안내 사이트 구축의 원천 데이터가 된다.

> 휴양림 총 개수는 탐색 시점(2026-05-06) 184곳 → 본 설계 시점(2026-06-03) 185곳으로 한 달 새 변동했다. 따라서 **개수를 코드에 하드코딩하지 않고** 매 수집 시 실제 응답 건수를 기준으로 처리한다.

## 결정된 요구사항

| 항목 | 결정 |
| --- | --- |
| 언어 | Python |
| 저장소 | SQLite |
| 수집 범위 | 휴양림 목록/기본정보 + 객실 목록/가격 + 할인/예약정책 + 공지사항 |
| 실행 방식 | 수동 CLI (주기 실행은 후속) |
| 키워드 추출 | 제외 — 이용안내/공지 원본 텍스트만 저장 (바베큐/물놀이 판정은 후속 고도화) |
| 공지 OCR | 제외 — 첨부 원본 다운로드까지만 (후속 고도화) |

## 아키텍처

단계별 파이프라인 CLI. 각 수집 단계를 독립된 서브커맨드로 분리하고, 단계 간에는 SQLite DB를 통해 데이터를 주고받는다.

### 핵심 원칙: fetch와 parse의 분리

- `crawlers/*`: HTTP 요청 → **raw 응답을 DB에 그대로 저장** → parser 호출 → 구조화 결과 저장
- `parsers/*`: raw HTML/JSON 문자열 → Python dict. **네트워크를 모르는 순수 함수**

이 분리의 이점:

1. 파싱 버그 발견 시 재요청 없이 DB의 raw에서 재파싱 가능 (`reparse` 커맨드)
2. parser는 fixture 파일로 단위 테스트 가능 (네트워크 불필요)
3. 사이트 구조 변경 시 fetch가 깨졌는지 parse가 깨졌는지 즉시 구분 가능

### 프로젝트 구조

```
jforest/
├── docs/                          # 기존 탐색 문서 + 본 설계
├── pyproject.toml                 # uv 패키지 정의
├── jforest/
│   ├── __main__.py                # python -m jforest 진입점
│   ├── cli.py                     # click 기반 서브커맨드
│   ├── db.py                      # SQLite 연결, 스키마 생성
│   ├── http.py                    # 공통 HTTP 클라이언트 (딜레이/재시도/UA/로깅)
│   ├── crawlers/
│   │   ├── forests.py             # 1단계: 휴양림 목록 (JSON id 목록 + HTML 목록 보강)
│   │   ├── rooms.py               # 2단계: 객실 목록
│   │   ├── room_details.py        # 3단계: 객실 상세 (가격/이용안내)
│   │   ├── discounts.py           # 4단계: 할인정책
│   │   ├── policies.py            # 5단계: 예약정책
│   │   └── notices.py             # 6단계: 공지사항 + 첨부 (목록 전체 페이지네이션)
│   └── parsers/
│       ├── forests.py             # JSON 목록 + HTML 목록 파서
│       ├── rooms.py               # crawlers와 대응하는 순수 파서
│       ├── room_details.py
│       ├── discounts.py
│       ├── policies.py
│       └── notices.py
├── data/
│   ├── jforest.db                 # SQLite DB
│   └── attachments/               # 공지 첨부파일 원본
└── tests/
    ├── fixtures/                  # 실제 HTML/JSON 응답 샘플
    └── ...                        # parser 단위 테스트
```

### 공통 HTTP 클라이언트 (`http.py`)

- 요청 간 기본 1초 딜레이 (공공 사이트 부하 배려)
- 타임아웃 + 지수 백오프 재시도 (3회)
- 일반 브라우저 User-Agent
- 모든 요청 결과를 `fetch_log` 테이블에 기록

## 데이터 모델 (SQLite 스키마)

원본 보존 계층과 구조화 계층을 분리하고, 모든 행에 수집 시각(`fetched_at`, ISO8601)을 기록한다.

### ① 원본 보존 계층

```sql
raw_pages (
  id INTEGER PRIMARY KEY,
  url TEXT NOT NULL,
  page_type TEXT NOT NULL,        -- forest_list_json | forest_list_html | room_list | room_detail | discount | policy_all | policy_detail | notice_list | notice_detail
  ref_key TEXT NOT NULL,          -- 연관 식별자 (sido 번호, html 페이지 번호, insttId, goodsId, twbbsId 등)
  http_status INTEGER,
  body TEXT NOT NULL,             -- 원본 HTML/JSON
  fetched_at TEXT NOT NULL,
  UNIQUE (page_type, ref_key)     -- 재수집 시 INSERT OR REPLACE로 최신 본문만 유지 (이력 보존 안 함)
)
```

`raw_pages`는 `(page_type, ref_key)`에 UNIQUE 제약을 두고 `INSERT OR REPLACE`로 적재해, 재실행 시 행이 무한 누적되지 않고 항상 최신 본문 1건만 유지한다. 한 휴양림에 여러 행이 생기는 단계는 `ref_key`를 **복합 키**로 구성해 덮어쓰기 충돌을 막는다: `policy_detail`은 `"{insttId}:{ruleId}"`, `notice_detail`은 `"{insttId}:{twbbsId}"`, `room_detail`은 `goodsId`. `reparse <단계>`는 해당 `page_type`의 모든 `raw_pages` 행을 읽어 구조화 테이블만 다시 채운다(네트워크 없음). 원본 이력 추적이 필요해지면 후속에 별도 모드를 추가한다.

### ② 구조화 계층

```sql
forests (
  instt_id TEXT PRIMARY KEY,      -- 'ID02030124', '0113' 등 (JSON insttId == URL hmpgId, 검증 대상)
  name TEXT NOT NULL,             -- 1a JSON insttNm (1b HTML로 보강 가능)
  sido_code INTEGER,              -- 1a: 수집에 사용한 srchSido 1~9 값
  arcd TEXT,                      -- 1a JSON arcd (지역코드 원본)
  instt_type_code TEXT,           -- 1a JSON insttTpcd (기관유형 코드)
  instt_type TEXT,                -- 1b HTML 기관구분 라벨 (국/공/사 등)
  homepage_url TEXT,              -- 1b HTML 전용
  tags TEXT,                      -- 1b HTML 전용. JSON 배열 (원본 태그)
  summary TEXT,                   -- 1b HTML 전용
  reservation_intake TEXT,        -- 1b HTML 예약 접수 유형 요약 (선착순/추첨/우선 등). 상세는 reservation_policies
  fetched_at TEXT NOT NULL
)
```

> **출처 분리 주의.** 라이브 검증 결과 `selectInsttHuyangList.do`(JSON)는 `insttId`, `insttNm`, `arcd`, `insttTpcd`만 반환하고 `tags`/`summary`/`homepage_url`은 모두 비어 있다. 이 필드들은 HTML 목록(`selectFcltSrchView.do`)에만 존재한다. 따라서 `forests`는 **두 단계**로 채운다:
>
> - **1a (JSON, srchSido 1~9)**: `instt_id`, `name`, `sido_code`, `arcd`, `instt_type_code` 적재 — 권위 있는 id/지역 목록.
> - **1b (HTML 목록 전체 페이지네이션)**: `insttId` 기준으로 `instt_type`(라벨), `homepage_url`, `tags`, `summary`, `reservation_intake`를 `UPDATE`로 보강.
>
> 1b의 HTML 목록 항목에 노출되는 식별자(예: `ID02030002`, `0113`)가 1a의 `insttId`와 일치해야 매칭된다. 매칭 실패 항목은 `fetch_log`에 기록한다.

```sql
rooms (
  goods_id TEXT PRIMARY KEY,      -- 'GID0203...'
  instt_id TEXT NOT NULL,         -- → forests
  room_type TEXT,                 -- '숲속의집', '산림휴양관' 등
  name TEXT,                      -- 'A동-101호(거류산)'
  capacity_standard INTEGER,
  capacity_max INTEGER,
  area TEXT,                      -- '20㎡'
  fetched_at TEXT NOT NULL
)

room_prices (
  id INTEGER PRIMARY KEY,
  goods_id TEXT NOT NULL,         -- → rooms
  season TEXT NOT NULL,           -- 정규화: off | peak (그 외 표기는 raw_label에 원본 보존)
  day_type TEXT NOT NULL,         -- 정규화: weekday | weekend (그 외는 raw_label)
  raw_label TEXT,                 -- 원본 요금 구분 문자열 (예: '준성수기 금요일' 등 2x2 밖 케이스)
  price INTEGER NOT NULL,
  fetched_at TEXT NOT NULL        -- "오늘일자 기준 가격" → 수집일 필수
)

-- 주의: 탐색 표본은 비수기/성수기 × 평일/주말 = 4행이었으나, 휴양림에 따라 준성수기·금요일·
-- 공휴일 등 추가 구분이 있을 수 있다. 파서는 행 수를 4로 고정하지 말고 표의 모든 요금 행을
-- 순회하며, 정규화 불가한 구분은 raw_label에 원본을 보존한다.

room_usage_texts (
  goods_id TEXT PRIMARY KEY,      -- → rooms
  checkin_time TEXT,
  checkout_time TEXT,
  amenities TEXT,                 -- 편의시설 원본 텍스트
  usage_guide TEXT,               -- 이용안내 원본 텍스트 (바베큐/물놀이 문구 포함, 추출은 후속)
  fetched_at TEXT NOT NULL
)

discount_policies (
  id INTEGER PRIMARY KEY,
  instt_id TEXT NOT NULL,         -- → forests
  target TEXT,                    -- 할인 대상 (예: '장애인 중증(1~3급)', '다자녀', '지역주민')
  category TEXT,                  -- 할인 구분 (예: '정율')
  timing TEXT,                    -- 할인 시점 (예: '결제시할인', '현장할인')
  apply_date TEXT,                -- 적용 일시 (검증 시 '2000-01-01' 등으로 노출)
  room_rates TEXT,                -- JSON: 비수기/성수기 × 주중/주말 할인율
  campsite_rate TEXT,
  facility_rate TEXT,
  fetched_at TEXT NOT NULL
)

reservation_policies (
  instt_id TEXT PRIMARY KEY,      -- → forests
  operates_rooms INTEGER,
  operates_campsite INTEGER,
  operates_waitlist INTEGER,
  fcfs_method TEXT,               -- 선착순 방식 (6주 수요일 / 익월말)
  lottery_types TEXT,             -- JSON: 주말추첨/성수기추첨
  priority_types TEXT,            -- JSON: 우선예약 종류
  fcfs_detail TEXT,               -- 개별 정책 페이지 상세 문구
  lottery_detail TEXT,
  fetched_at TEXT NOT NULL
)

notices (
  instt_id TEXT NOT NULL,         -- → forests
  twbbs_id TEXT NOT NULL,
  title TEXT,
  updated_at TEXT,                -- 공지 수정일
  body_text TEXT,                 -- HTML 태그 제거한 본문
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (instt_id, twbbs_id)
)

notice_attachments (
  id INTEGER PRIMARY KEY,
  instt_id TEXT NOT NULL,
  twbbs_id TEXT NOT NULL,         -- → notices
  file_master_id TEXT,
  file_id TEXT,
  file_name TEXT,
  content_type TEXT,
  local_path TEXT,                -- data/attachments/ 저장 경로
  downloaded INTEGER DEFAULT 0,
  fetched_at TEXT NOT NULL
)
```

### ③ 운영 계층

```sql
fetch_log (
  id INTEGER PRIMARY KEY,
  url TEXT,
  http_status INTEGER,
  error TEXT,                     -- 실패 시 에러 메시지 (성공이면 NULL)
  duration_ms INTEGER,
  fetched_at TEXT NOT NULL
)
```

### 갱신 전략

재수집 시 같은 키(PK)는 `INSERT OR REPLACE`로 덮어쓰며 `fetched_at`이 갱신된다. `room_prices`는 PK가 자동 증가 ID이므로, 재수집 시 해당 `goods_id`의 기존 행을 삭제 후 재삽입한다. 가격 이력 추적은 초기 범위에서 제외하며, 필요해지면 이력 보존 모드를 추가한다.

## 데이터 흐름 / CLI 커맨드

```
crawl forests ──→ crawl rooms ──→ crawl room-details
  (1a JSON         │
   + 1b HTML)      ├──→ crawl discounts
                   ├──→ crawl policies
                   └──→ crawl notices ──→ crawl attachments

crawl all          # 전체를 순서대로 실행
reparse <단계>      # raw_pages에서 재파싱만 (네트워크 X)
status             # 단계별 수집 현황 요약
```

`crawl forests`는 내부적으로 1a(JSON, srchSido 1~9)와 1b(HTML 목록 전체 페이지)를 순서대로 실행한다.

공통 옵션:

- `--limit N`: 휴양림 N곳만 처리 (스모크 테스트용)
- `--force`: 이미 수집된 항목도 다시 수집 (기본은 resume — 건너뜀)
- `--delay SECONDS`: 요청 간 딜레이 조정 (기본 1초)

각 단계는 이전 단계의 DB 데이터를 입력으로 사용한다. 예: `rooms`는 `forests`의 `instt_id` 목록을 순회한다.

**공지 수집 범위 / 페이지네이션 (검증 완료)**: `crawl notices`는 각 휴양림 공지 목록을 **전체 페이지** 수집한다. 라이브 검증으로 확정한 프로토콜:

- 프론트엔드는 `fripPotForm`(method=POST)에 `nowPage`를 넣어 전송하지만, **크롤링은 동일 URL에 GET 쿼리 `&nowPage=N`(N≥1)을 붙이면 동작**한다. POST는 빈 결과를 반환했고 GET+`nowPage`는 정상적으로 N페이지를 반환했다.
- 마지막 페이지 감지: `nowPage`가 최대치를 넘으면 빈 페이지가 아니라 **마지막 페이지로 clamp**된다(예: `nowPage=999`도 마지막 페이지 반환). 따라서 "빈 목록"으로 종료를 판단하면 안 된다. 대신 **목록 HTML에 박혀 있는 `totPage` 값을 파싱**(예: `totPage = 5`)해 `nowPage`를 `1..totPage`로 순회한다.
- 공지 식별자는 `fn_goDtlView('261671')` 형태로 raw HTML에서 추출한다.

별도 메뉴 확인 단계는 두지 않는다 — 공지 메뉴(`menuId=005001`, `bbrssMsterId=BBRSSMSTER_00000051`)가 공통 상수로 검증됐기 때문이다. 객실/할인/예약 메뉴가 없는 휴양림(예: 야영장만 운영)은 빈 응답을 `not_available`로 처리한다.

## 에러 처리

| 상황 | 처리 |
| --- | --- |
| HTTP 타임아웃/5xx | 지수 백오프로 3회 재시도 후 `fetch_log`에 기록하고 다음 항목 진행 |
| 파싱 실패 (예상 구조와 다름) | raw는 저장된 상태이므로 에러 로그만 남기고 계속. 이후 `reparse`로 복구 |
| 휴양림에 해당 메뉴 없음 (예: 객실 미운영) | 정상 케이스로 처리, `fetch_log`에 not_available 기록 |
| 중간 중단 (Ctrl+C) | 이미 저장된 항목 유지, 재실행 시 이어서 수집 |

실행 종료 시 요약 출력: `성공 N건 / 건너뜀 N건 / 실패 N건` + 실패 목록.

## 수집 경로 (탐색 문서에서 확정된 URL 패턴)

| 단계 | URL 패턴 | page_type | 비고 |
| --- | --- | --- | --- |
| 휴양림 목록(1a) | `/pot/rm/cs/selectInsttHuyangList.do?srchSido={1..9}` | forest_list_json | id/이름/arcd/유형코드만. ref_key=sido 번호 |
| 휴양림 목록(1b) | `/pot/is/fs/selectFcltSrchView.do?hmpgId=FRIP&menuId=002001` | forest_list_html | 약 47페이지. tags/summary/홈페이지/예약접수 보강. **페이지네이션 전체 순회**. ref_key=페이지 번호 |
| 객실 목록 | `/pot/rm/fa/selectFcltsArmpListView.do?hmpgId={insttId}&menuId=002002001` | room_list | |
| 객실 상세 | `/pot/rm/fa/selectFcltsArmpDtlView.do?insttId={insttId}&goodsId={goodsId}` | room_detail | |
| 할인정책 | `/pot/rm/ug/selectDcPolicyView.do?hmpgId=FRIP&menuId=002004&insttId={insttId}` | discount | |
| 예약정책(전체) | `/pot/cc/bb/selectFripRsrvtPolcyView.do?hmpgId=FRIP&menuId=002002` | policy_all | 전체 표 1회 수집 |
| 예약정책(개별) | `/pot/rm/ug/selectRsrvtGdncView.do?hmpgId={insttId}&menuId={004001001\|002\|003}&ruleId={101\|102\|103}` | policy_detail | 101 선착순 / 102 주말추첨 / 103 성수기추첨. 전체 표에서 운영 종류 확인 후 해당 정책만 수집 |
| 공지 목록 | `/pot/cc/nm/selectNticBbrssListView.do?hmpgId={insttId}&menuId=005001&bbrssMsterId=BBRSSMSTER_00000051` | notice_list | **전체 페이지 순회** |
| 공지 상세 | `/pot/cc/nm/selectNticBbrssDtlView.do?hmpgId={insttId}&menuId=005001&twbbsId={twbbsId}&bbrssMsterId=BBRSSMSTER_00000051` | notice_detail | |
| 첨부 다운로드 | `/com/cm/fileDownload.do?ATTCH_FILE_ID={fileId}&ATTCH_FILE_MSTER_ID={fileMasterId}` | (바이너리, raw_pages 미저장) | |

주의:

- 공지 목록 URL은 반드시 `menuNm == "공지사항"` 하위 메뉴(`menuId=005001`)를 쓴다. 상위 메뉴 URL은 `bbrssMsterId`가 잘릴 수 있다(탐색 문서).
- **`insttId == hmpgId` (검증 완료)**: JSON 목록의 `insttId`(예: `ID02030019`)를 `selectMenuList.do?hmpgId=ID02030019`에 넣으면 메뉴 URL이 `hmpgId=ID02030019`로 생성됨을 라이브로 확인했다. 즉 JSON `insttId`를 그대로 모든 URL의 `hmpgId`로 사용한다. 안전장치로 `crawl forests` 직후 표본 몇 곳의 메뉴 호출 200 여부만 가볍게 assert한다.
- **공지 메뉴 상수 (검증 완료)**: `selectMenuList.do` 응답에는 여러 게시판(`BBRSSMSTER_00000051/52/53/365` 등)이 섞여 있으나, `menuNm == "공지사항"` 항목은 `menuId=005001` + `bbrssMsterId=BBRSSMSTER_00000051`로 확인됐다. 반드시 `menuNm == "공지사항"`으로 골라야 한다.
- **첨부 파일 종류 판별**: `content_type`(`Content-Disposition`/`Content-Type` 헤더)만 신뢰하지 않고, 다운로드한 파일의 **매직바이트(파일 시그니처)** 로 실제 종류를 함께 판별해 `notice_attachments.content_type`에 보정 저장한다(탐색 문서 권고). 첨부 인자는 `fn_goFileDown('FILEMSTER_...', '184669')` 형태로 raw HTML에서 추출(검증 완료).
- **`goodsId` 추출 위치 (검증 완료)**: 객실 목록 페이지는 서버 렌더 HTML이지만 `goodsId`(예: `GID020301240100101001001000004`)가 plain `href`가 아니라 JS 핸들러/링크 템플릿 안에 `goodsId=GID...` 형태로 들어있다. 마크다운 변환 도구는 이를 제거하므로 **반드시 raw HTML에서 정규식/DOM으로 추출**한다(아키텍처의 raw 보존 파싱과 일치).

## 라이브 프로토콜 검증 결과 (2026-06-03)

아래는 실제 사이트에 요청해 확인한 사실이다. 사용 샘플: `hmpgId=ID02030124`(고성갈모봉, `goodsId=GID020301240100101001001000004`), `hmpgId=0113`(가리왕산, `twbbsId=250396`), `insttId=ID02030019`(강씨봉).

| 항목 | 검증 결과 |
| --- | --- |
| JSON 목록 필드 | `insttId`, `insttNm`, `arcd`, `insttTpcd`만 반환. `tags`/`summary`/`homepage`는 빈 값. sido=1이 26곳(탐색 시 25곳 → 변동) |
| HTML 목록 | 서버 렌더, 약 47페이지 185곳. `tags`/`summary`/홈페이지/예약접수유형/기관구분 라벨 포함 |
| `insttId == hmpgId` | 일치 확인 (JSON `insttId`가 메뉴/객실/공지 URL의 `hmpgId`로 그대로 동작) |
| 공지 메뉴 상수 | `menuNm=="공지사항"` → `menuId=005001`, `bbrssMsterId=BBRSSMSTER_00000051` 확인 |
| 객실 목록 | 서버 렌더 HTML. `goodsId=GID...`가 JS 핸들러 내부에 존재 (raw HTML 파싱 필요) |
| 객실 상세 | 기준/최대인원, 면적, 편의시설, 입퇴실(15:00~11:00), 가격표(비수기/성수기 × 평일/주말), "오늘일자 기준 가격정보" 문구, 이용안내 텍스트 확인 |
| 할인정책 | 할인대상/구분/시점/적용일시/객실(비수기·성수기 주중·주말)/야영장/부대시설 할인율 표. 서버 렌더 |
| 예약정책(전체) | 단일 페이지에 전 휴양림 행. 구분/지역/휴양림/운영현황/예약방법/우선예약 컬럼 |
| 예약정책(개별) | `selectRsrvtGdncView.do?hmpgId=&menuId=004001001&ruleId=101` 동작(선착순 문구 확인) |
| 공지 목록 식별자 | `fn_goDtlView('261671')` 형태로 `twbbsId` 추출 |
| 공지 페이지네이션 | **GET `&nowPage=N`으로 동작**(POST는 빈 결과). 초과 시 마지막 페이지로 clamp → HTML의 `totPage` 값을 파싱해 `1..totPage` 순회 |
| 공지 첨부 | `fn_goFileDown('FILEMSTER_00172858','184669')` 인자 추출. 다운로드는 `fileDownload.do?ATTCH_FILE_ID=&ATTCH_FILE_MSTER_ID=` |

## 테스트 전략

- **parser 단위 테스트 (핵심)**: 실제 사이트 응답 HTML/JSON을 `tests/fixtures/`에 저장하고 각 parser의 반환 구조를 검증. 네트워크 불필요. 위 샘플 응답을 그대로 fixture로 사용한다.
- **crawler 통합 테스트**: HTTP 클라이언트를 mock으로 대체해 fetch→파싱→DB 저장 흐름 검증.
- **실제 사이트 스모크 테스트**: `--limit 2`로 휴양림 2곳만 실제 수집해 전체 파이프라인 확인 (수동 실행).

## 기술 스택

| 용도 | 라이브러리 |
| --- | --- |
| 패키지 관리 | uv |
| HTTP | httpx |
| HTML 파싱 | selectolax |
| CLI | click |
| DB | 표준 라이브러리 sqlite3 (ORM 없음) |
| 테스트 | pytest |

## 범위 밖 (후속 고도화)

- 바베큐/물놀이 키워드 추출 및 긍정/부정 문맥 판정
- 공지 첨부(JPG/PDF) OCR 및 구조화
- 주기적 자동 실행 (cron/스케줄러)
- 가격 이력 추적
- 실시간 빈 객실/예약 가능 여부 (NetFunnel/로그인 흐름 필요)

## 검토 이력 (2026-06-03 라이브 검증 후 수정)

초안을 라이브 사이트와 대조해 다음 문제를 발견·수정했다.

| # | 발견한 문제 | 수정 |
| --- | --- | --- |
| A | `forests`의 `tags`/`summary`/`homepage_url`을 JSON 목록(`selectInsttHuyangList.do`)에서 채울 수 있다고 가정 → 실제 JSON은 `insttId/insttNm/arcd/insttTpcd`만 반환 | 1a(JSON id 목록) + 1b(HTML 목록 보강) 두 단계로 분리, 컬럼 출처 명시 |
| B | 공지 수집이 첫 페이지만인지 전체인지 미정 | 목록 전체 페이지네이션 수집으로 명시 |
| C | `raw_pages` 재실행 시 무한 누적 + `reparse` 대상 행 모호 | `UNIQUE(page_type, ref_key)` + `INSERT OR REPLACE`, 복합 ref_key 규칙 명시 |
| D | 불필요한 `menus` 단계 | 제거 (공지 menuId/bbrssMsterId가 전 휴양림 공통 상수) |
| E | `insttId == hmpgId` 미검증 가정 | `crawl forests` 직후 assert 검증 절차 추가 |
| F | `room_prices`가 2×2=4행 고정 가정 | 가변 행 수용 + `raw_label` 원본 보존 |
| G | 첨부 파일 종류를 헤더만으로 판별 | 매직바이트 검증 추가 |
| H | 휴양림 개수 하드코딩 위험 (184→185 변동) | 하드코딩 금지, 실제 응답 건수 기준 |

### 2차: 라이브 프로토콜 검증 (curl/WebFetch로 실측)

초안의 URL·필드·프로토콜을 실제 사이트로 검증하고 다음을 확정·수정했다. 상세는 위 "라이브 프로토콜 검증 결과" 표 참조.

- `insttId == hmpgId`, 공지 메뉴 상수(`005001`/`BBRSSMSTER_00000051`)를 **가정에서 검증 완료로 승격**.
- **공지 페이지네이션 메커니즘 확정**: GET `&nowPage=N` + HTML `totPage` 파싱 (POST·빈페이지 종료 방식은 오동작). 이는 초안에 없던 중요한 구현 제약.
- **`goodsId`는 raw HTML의 JS 핸들러에서 추출**해야 함을 확인 (마크다운 변환으로는 유실).
- 할인정책에 `apply_date`(적용일시) 컬럼 추가.
- 첨부 인자 형식 `fn_goFileDown('FILEMSTER_...','fileId')` 확인.
