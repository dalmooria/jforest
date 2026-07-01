# 날짜별 예약오픈 안내 서비스 설계 (Open Report)

**Goal:** 이미 적재된 데이터를 파싱해, 사용자가 **웹에서 날짜를 고르면 그날 예약창이 열리는 휴양림 리스트**(선착순·추첨·지역주민 + 시설·지역·오픈시각)를 보여준다. 여기에 공사/예약제외 같은 **동적 예약불가 정보**를 주기적으로 수집해 배지로 반영한다.

**출력 예시(사용자 관점):**
```
7월 2일 (목) 예약 오픈 — 총 N곳
━━ 선착순 ━━
생거진천자연휴양림 / 충북 · 선착순 · 오후 1시 · 물놀이(O) 바베큐(O) 숲해설(O) · 6주차(~8/12 화) 예약가능
━━ 추첨 ━━
유명산자연휴양림 / 경기 · 주말추첨 · 오전 9시 · 물놀이(△) 바베큐(X) · ⚠ 7/14까지 일부 예약불가(공사)
━━ 지역주민 ━━
용인자연휴양림 / 경기 · 지역주민 우선 · 오전 9시 · 물놀이(△) 바베큐(△)
```

**Tech Stack:** 기존 스택 재사용 — Python 3.11+, sqlite3(`data/jforest.db`), FastAPI + uvicorn(`jforest/api.py`, inline HTML), click CLI, pytest.

**참조:** `docs/foresttrip-exploration.md`(소스 사이트 리버스), `jforest/fcfs_report.py`(기존 선착순 리포트).

---

## 1. 스코프 & 확정 결정

| 항목 | 결정 |
| --- | --- |
| 예약 타입 | **선착순 + 추첨 + 지역주민 + 일반오픈(15일)**. 자격제한 우선예약(바우처·장애인·실버·아세안)은 제외 |
| 성수기추첨 | 매월 날짜매칭에서 제외, 하단 **고정 안내**로만 표기 |
| 파싱 미상 채널 | **숨기지 않고 노출** — 해당 타입 섹션 하단에 `⚠ 일정 확인 필요` 블록 |
| 15일 일반오픈 | 추첨 미선정·취소분 선착순 전환 → **포함** (선착순 그룹, `일반오픈(미선정분)`) |
| 출력 그룹핑 | **타입별**(선착순 → 추첨 → 지역주민 → 성수기), 그룹 내 지역 가나다 |
| 코드 구조 | 기존 `fcfs_report.py` **확장**(기존 15개 테스트 보존), 신규 함수 추가 |
| 서비스 형태 | **FastAPI 웹** — 날짜 선택 UI + JSON API |

---

## 2. 아키텍처 (4층)

```
data/jforest.db (sqlite, 구축 완료)
      ↓ [로직층]  파싱·매칭·enrich
jforest/fcfs_report.py :: build_open_events(conn, date) → list[event]
      ↓ [API층]   JSON
jforest/api.py :: GET /api/open-report?date=&type=&region=
      ↓ [웹UI층]  inline HTML
jforest/api.py :: GET /open  (날짜 선택 페이지)
      ↓
브라우저: <input type=date> → fetch → 타입별 렌더
```

기존 `/`(챗)·`/ask`는 그대로, 라우트만 추가. 실행: `jforest agent serve --port 8000` → `http://localhost:8000/open`.

---

## 3. Phase 1 — 정적 스케줄 리포트 + 웹

### 3.1 데이터 소스 & 예약 타입 분류

**분류는 `rule_id`가 authoritative** (title 키워드는 `104 지역주민우대추첨제`처럼 "추첨"·"지역주민" 동시 포함 → 오분류하므로 사용 금지). 실측 rule_id 전체 = {101,102,103,104,105,106,107,108,111,112,211}.

| rule_id | 정책명 | type_group | 오픈 스케줄 소스 |
| --- | --- | --- | --- |
| 101 | 선착순 | **선착순** | `reservation_policies.fcfs_method`(기존 `_classify`) — policy_details 아님 |
| 102 | 주말추첨 | **추첨** | detail 파싱 → 폴백 매월 4일 오전9시 |
| 103 | 성수기추첨 | **성수기(별도)** | 매월매칭 제외 → seasonal_note 고정 |
| 111 | 월추첨 | **추첨** | detail 파싱 → 폴백 매월 1일 오전9시 |
| 104 | 지역주민우대추첨 | **지역주민** | detail 파싱(공립별 상이) |
| 105 | 지역주민우선예약 | **지역주민** | detail 파싱(공립별 상이) |
| 106,107,108,112,**211** | 실버·바우처·장애인·관광취약·**다자녀** | **제외(자격제한)** | — |
| — | 일반오픈(미선정분) | **선착순** | 파생: 102 보유 휴양림 대상, 상수 매월 15일 오전9시 |

**결정(신규):** `211 다자녀`는 rule_id에 "다자녀우선예약"(36)·"다자녀추첨"(4)이 혼재하고 자격제한(2자녀 이상)이므로, 바우처·장애인과 동일하게 **전체 제외**(스코프의 "추첨"은 일반접근 주말·월추첨을 의미).

**일반오픈 파생 규칙:** rule_id 102(주말추첨)를 보유한 휴양림(=국립 46곳)만 매월 15일 일반오픈 채널을 생성.

지역 매핑(`forests.sido_code` → 이름, 실측 역추론 검증):
```
1 경기·인천 / 2 강원 / 3 충북 / 4 충남·대전 / 5 전북 /
6 전남·광주 / 7 경북·대구 / 8 경남·부산·울산 / 9 제주
```

### 3.2 파싱 전략 (3단 폴백 — 실데이터 516행 측정)

1. **정규화**: NFKC + 모든 공백 단일화 (HWP 추출의 글자단위 줄바꿈 제거 — 필수)
2. **앵커+정규식**: `예약신청`/`신청 접수 기간`/`추첨예약신청` 앵커를 찾고, **앵커부터 다음 섹션 마커(`○`/`- `/`※`) 직전까지의 한 세그먼트 안에서만** 첫 날짜+시각 추출.
   - ⚠ 고정폭 120자 창은 금지: `당첨자 발표 : 매월 5일` 같은 뒤 섹션 날짜를 오탐함. 반드시 섹션 경계로 절단.
   - 날짜: `매월 N일`(monthly) / `매주 X요일`·앵커직후 `X요일`(weekly)
   - 시각: `오전/오후 N시` / `HH:MM`. **없으면 `open_time=None`(날조 금지)**
3. **국립 표준 상수 폴백**(파싱 실패 시):
   `주말추첨=매월 4일 오전9시` / `월추첨=매월 1일 오전9시` / `미선정 일반오픈=매월 15일 오전9시`. 상수는 rule_id가 국립 표준일 때만 적용(공립엔 미적용).
4. **graceful degradation**: 날짜 파싱까지 실패 → 버리지 않고 `confidence="미상"` + `reservable_label="일정 확인 필요"`. (시각만 없으면 `confidence="확정"` 유지, 시각만 "미상")

**측정 커버리지(수정 설계로 재검증 2026-07-01):**
- 선착순 시각: 국립 48/48, 공립 115/137(**22곳 시각 None**, 예: 생거진천 `ID02030033`=익월말·시각없음).
- 추첨: **53/53 노출가능**(확정 5 + 상수폴백 48), 미상 0.
- 지역주민: **27/47 확정(~57%) + 20곳 미상 노출**. 섹션경계 절단으로 오탐(잘못된 날짜)=0 우선 → 미상은 `⚠ 일정 확인 필요`. 앵커/패턴 확장으로 개선 여지(구현 중 반복).
- 성수기추첨(103)=연1회·고정일 없음 → 매월매칭 제외.

### 3.2b 채널 병합 & 라벨 규칙 (신규 — 결함 수정)

**중복 병합:** 53개 휴양림이 in-scope rule 2~3개 보유. 한 대상일 D에서 **(instt_id, type_group, open_time)가 같은 채널은 1행으로 병합**하고 `type_label`을 `"주말추첨·지역주민 우선"`처럼 결합. 그룹/날짜가 다르면 자연 분리됨.

**type_group별 reservable_label**(선착순 전용 "6주차" 로직 일반화):
| type_group | kind | 라벨 |
| --- | --- | --- |
| 선착순 | weekly | `N주차(~MM/DD 요일) 예약가능` (기존 `_reservable_label`) |
| 선착순 | monthly(익월말) | `익월 말일 이용분 예약가능` |
| 선착순 | 일반오픈 | `추첨 미선정·취소분 오픈` |
| 추첨 | monthly | `다음달 이용분 접수 시작` |
| 지역주민 | weekly/monthly | `지역주민 우선 접수` |
| (미상) | — | `일정 확인 필요` |

### 3.3 데이터 모델 — 예약채널(open event)

한 휴양림 = 여러 채널. 채널 = `(휴양림, 예약타입, 스케줄)`. 대상일 D에 오픈일이 걸리는 채널을 나열.
```python
{
  "instt_id", "name", "region",
  "type_group": "선착순|추첨|지역주민",
  "type_label": "선착순|주말추첨|월추첨|일반오픈(미선정분)|지역주민 우선| (병합 시 '·'로 결합)",
  "kind": "weekly|monthly",
  "open_time": "오전 9시" | None,               # None → UI '시각 미상'(날조 금지)
  "reservable_label": "6주차(~7/21 화) 예약가능" | "다음달 이용분 접수 시작" | "일정 확인 필요",
  "confidence": "확정|추정|미상",                 # 미상=날짜 파싱 실패, 추정=상수폴백
  "time_confidence": "확정|미상",                # 시각 결측 구분(날짜와 독립)
  "water_play","barbecue","forest_guide",       # O|X|△(정보없음/needs_review)
  "alerts": [ ... ],                             # Phase 2에서 채움
}
```
병합 후 산출물이므로 한 (instt_id, group)당 대상일 최대 1행.

### 3.4 모듈 변경 (`fcfs_report.py` 확장)

기존 함수·테스트 그대로 두고 추가:
```
SIDO(dict), _region(), _normalize(), parse_open_event(detail_text, rule_id),
_type_group(title), _type_label(title), _open_time_from_fcfs(detail),
NATIONAL_DEFAULTS(dict), build_open_events(conn, on_date), format_open_report(events, on_date)
```
`build_open_events` 흐름: 선착순(기존 `_classify` 재사용 + 시각/지역 enrich) + 추첨·지역주민(`reservation_policy_details` 순회 → 필터 → `parse_open_event` → D매칭) + 일반오픈(상수) → 지역/시각/시설/confidence enrich.

**참조 시그니처 & 의사코드(구현 확정용):**
```python
RULE_GROUP = {"101":"선착순","102":"추첨","111":"추첨","104":"지역주민","105":"지역주민"}
# 103=성수기(별도), 106/107/108/112/211=제외
NATIONAL_DEFAULT = {"102":("monthly",4,"오전 9시"), "111":("monthly",1,"오전 9시")}
GENERAL_OPEN = ("monthly", 15, "오전 9시")   # 일반오픈: 102 보유 휴양림

def parse_open_event(detail_text, rule_id):
    """→ dict(kind,key,open_time,time_conf) | None(날짜 파싱 실패)."""
    t = _normalize(detail_text)                       # NFKC + 공백단일화
    seg = _anchored_segment(t)                        # 앵커~다음 마커(○/-/※) 전까지
    kind, key = _match_date(seg)                      # 매월N일 | 매주X요일 | 앵커직후 X요일
    if kind is None:
        d = NATIONAL_DEFAULT.get(rule_id)             # 상수 폴백(국립만)
        return {**_as(d), "conf":"추정"} if d else None
    tm = _match_time(seg)                             # 오전/오후N시 | HH:MM | None
    return {"kind":kind,"key":key,"open_time":tm,"time_conf":"확정" if tm else "미상","conf":"확정"}

def build_open_events(conn, on_date):
    events = []
    # (1) 선착순: 기존 _classify(reservation_policies) 재사용
    for r in _fcfs_rows(conn):
        ev = _classify(r["fcfs_method"], r["fcfs_detail"])
        if ev and _opens_on(ev, on_date):
            events.append(_mk(r, "선착순", ev, open_time=_open_time_from_fcfs(r), conf="확정"))
    # (2) 추첨·지역주민: policy_details 순회
    for r in _detail_rows(conn):                      # JOIN forests, facilities
        g = RULE_GROUP.get(r["rule_id"])
        if not g: continue                            # 103/제외군 skip
        pe = parse_open_event(r["detail_text"], r["rule_id"])
        if pe is None:
            events.append(_mk(r, g, None, conf="미상")); continue   # 미상 노출
        if _opens_on(pe, on_date):
            events.append(_mk(r, g, pe, conf=pe["conf"]))
    # (3) 일반오픈: 102 보유 휴양림, on_date.day==15
    if on_date.day == 15:
        for r in _forests_with_rule(conn, "102"):
            events.append(_mk(r, "선착순", _as(GENERAL_OPEN), type_label="일반오픈(미선정분)", conf="추정"))
    return _merge_and_sort(events)                    # (instt_id,group,open_time) 병합 → 그룹/지역 정렬 → 미상 뒤로
```
`_opens_on`(기존)·`_classify`(기존)·`_reservable_label`(기존, 선착순 weekly용)은 재사용. `_merge_and_sort`가 3.2b 병합·정렬 규칙 담당.

### 3.5 API 엔드포인트

| 메서드 | 경로 | 응답 |
| --- | --- | --- |
| GET | `/open` | HTML (날짜 선택 UI) |
| GET | `/api/open-report?date=YYYY-MM-DD` | JSON. `&type=추첨`·`&region=충북` 필터(선택) |

- 잘못된 date(형식/`date.fromisoformat` 실패) → **400**. 생략 → 오늘(**KST**: `datetime.now(ZoneInfo("Asia/Seoul")).date()`, 서버 TZ 무관).
- DB: **요청당 read-only 연결** — `sqlite3.connect(f"file:{os.path.abspath(db_path)}?mode=ro", uri=True, check_same_thread=False)`, `row_factory=Row`, 요청 끝 `close()`. 크롤러가 쓰는 중(WAL)이어도 ro 리더는 락 안 걸림. 1.4GB지만 조인 키가 전부 PK/인덱스라 지연 무시가능.

**JSON 스키마(Pydantic):**
```jsonc
{
  "date":"2026-07-02", "weekday":"목", "total":37,
  "groups":[ { "type_group":"선착순","count":12,"uncertain_count":0,
               "events":[ {OpenEvent...} ] }, ... ],
  "seasonal_note":"성수기추첨: 매년 5월말~6월 접수 / 이용 7·8월 / 45개 국립휴양림"
}
```
정렬: 선착순→추첨→지역주민, 그룹 내 확정 먼저(지역 가나다) → 미상 뒤로.

### 3.6 웹 UI (inline HTML, 기존 톤 재사용)

- 상단: `◀ [날짜입력] ▶`(±1일), 지역 필터 드롭다운
- 타입별 섹션 카드: 휴양림명·지역·타입·오픈시각·시설배지(O초록/X회색/△노랑)·confidence뱃지
- `⚠ 일정 확인 필요`·`⚠ 예약불가(공사)`는 접힘/배지 처리
- 하단: 성수기추첨 고정 안내 + "정책·공사 기반 안내이며 실시간 잔여석과 다를 수 있음" 고지

**반응형 요건 (모바일 필수 지원) — 검증가능 체크리스트:**
- `<meta name="viewport" content="width=device-width, initial-scale=1">` (기존 `CHAT_HTML`과 동일)
- **모바일 우선 + 단일 브레이크포인트**: 기본 단일 컬럼(폰), `@media (min-width: 768px)`에서 카드 2열/여백 확대(태블릿·데스크톱)
- **유동 레이아웃**: 고정 px 폭 금지, `max-width` + `%`/`clamp()`/`flex-wrap`. 가로 스크롤 0
- **터치 타깃**: `◀ ▶`·필터·카드 등 인터랙션 요소 최소 **44×44px**, 요소 간 간격 ≥8px
- **입력 확대 방지**: 폼 입력 `font-size: 16px` 이상(iOS 자동 줌 방지). 날짜는 네이티브 `<input type="date">` 피커
- **시설/타입 배지 `flex-wrap`**: 좁은 화면에서 자연 줄바꿈
- **safe-area**: 하단 고정 요소 사용 시 `env(safe-area-inset-bottom)` 패딩(노치 대응)
- **성능**: 외부 프레임워크 無, inline CSS/JS만(기존 패턴) → 모바일 네트워크에서도 즉시 렌더

**검증 방법:**
- 개발: Playwright(이미 세션 MCP로 사용가능)로 뷰포트 375×667(모바일)·768(태블릿)·1280(데스크톱) 스크린샷 + 가로 스크롤 없음 assert
- API 테스트와 별개로 UI는 수동/스크린샷 검증 (자동화 최소)

---

## 4. Phase 2 — 동적 예약불가 정보 (공사·예약제외·휴관)

### 4.1 소스
이미 `notices`에 존재(공사/예약제외/휴관/점검 **1031건**). 제목·본문·첨부(예약제외 시설물 PDF/HWP)에 대상 휴양림·객실·기간·사유 포함. 예: `"...유지보수공사 일정변경 알림(2026.6.3.~7.14.)"`.

### 4.2 4단계 주기 파이프라인

1. **증분 크롤** — `crawlers/notices.py run()`이 기존 twbbs_id를 이미 skip → 재실행 = 신규만 fetch.
   - 보완①: *내용만 갱신*된 동일 twbbs_id(월초 '예약제외 현황')는 현재 skip됨 → 리스트페이지 `updated_at` 비교해 최신이면 재fetch.
   - 최적화: 잦은 실행은 각 휴양림 **1페이지만** 크롤.
2. **분류/필터** — 제목 키워드 규칙 프리필터 → `{공사,예약제외,휴관,점검,재해,행사}` 후보만 LLM에.
3. **구조화 추출**(LLM, 기존 `structure.py` 인프라 재사용) → 신규 테이블:
   ```
   reservation_blocks(
     id, instt_id, alert_type(공사|예약제외|휴관|점검|재해|행사),
     scope(전체|객실|야영장|프로그램), affected_units,
     start_date, end_date, reason, source_twbbs_id, needs_review, extracted_at)
   ```
   난관 = **기간 파싱**(`2026.6.3.~7.14.`, `당분간`, `별도공지시까지`) → 무기한형 `end_date=null`, `needs_review` 플래그.
4. **리포트 반영** — `build_open_events`가 대상일 활성 block 조인 → 배지(`⚠ 7/14까지 일부 예약불가(공사)`). 전체 휴관은 별도 "이용불가" 섹션.

### 4.3 스케줄링
→ **§9 일일 갱신(Daily Refresh) 설계**로 통합.

### 4.4 한계 (UI에 명시 필요)
- **실시간 빈방(매진)은 미커버.** 특정 객실 특정일 마감 여부 = foresttrip 예약 캘린더(`useDtList`/NetFunnel/**로그인 세션**) 필요, docs에 out-of-scope 기록됨. notices 기반은 공사·정책성 차단만 커버.

---

## 5. 파일 변경 계획

| 파일 | 변경 | Phase |
| --- | --- | --- |
| `jforest/fcfs_report.py` | 로직 추가(기존 유지) | 1 |
| `jforest/api.py` | `/api/open-report`·`/open` 라우트 + `OPEN_HTML` + Pydantic 모델 | 1 |
| `jforest/cli.py` | `open-report --date`(터미널), `alerts-extract`, `crawl notices --incremental` 보완 | 1·2 |
| `jforest/db.py` | `reservation_blocks` 테이블 DDL | 2 |
| `jforest/crawlers/notices.py` | `updated_at` 비교 증분 보완 | 2 |
| `jforest/alerts.py`(신규) | 공지 분류 + LLM 구조화 | 2 |
| `tests/test_open_report.py` | 로직 단위(파서·매칭·미상) | 1 |
| `tests/test_api_open_report.py` | `fastapi.testclient`(shape·400·필터) | 1 |
| `tests/test_alerts.py` | 기간 파싱·분류 | 2 |

---

## 6. 구현 순서

**Phase 0 — 데이터 리프레시(선행, §7b)**
0. `jforest crawl policies` 재실행(또는 저장 raw로 `reparse`) → `reservation_policies` 정합화(상세정책 소멸). 비FRIP 14곳 `정책 정보없음` 태깅. 검증: `상세정책` 카운트 ≤ (비FRIP 잔여).

**Phase 1**
1. `fcfs_report.py` 로직층 + 단위테스트(파서 커버리지 확보)
2. `api.py` JSON 엔드포인트 + API 테스트
3. `/open` HTML UI
4. `cli.py` 터미널 명령(선택)

**Phase 2**
5. `db.py` `reservation_blocks` + `crawlers/notices.py` 증분 보완
6. `alerts.py` 분류+구조화 + 테스트
7. `build_open_events`에 block 조인 + UI 배지
8. cron 스케줄 문서화

---

## 7. 미해결/리스크
- 지역주민(105) 프로즈 편차 → 미상 비율 관리(현재 ~31%). 규칙 확장 여지.
- 기간 파싱 정확도가 Phase 2 품질 좌우 → `needs_review` 리뷰 루프 필요.
- **국립 46곳 대량 노출**: 매월 4일(주말추첨)·15일(일반오픈)엔 국립 46곳이 동시 등장 — 정상이나 UI에서 지역/그룹 필터·접힘으로 가독성 확보.
- 지역주민 weekly(매주 월요일 등)는 "매주 반복" 성격 → 라벨에 반영("매주 X요일 지역주민 접수") 고려.
- **선착순 시각 결측 22곳**은 `time_confidence="미상"`으로 노출(오전9시 등 날조 금지).

## 7b. 라이브 소스 대조 검증 (2026-07-01) — ⚠ 선행 데이터 리프레시 필요

라이브 `selectFripRsrvtPolcyView.do?hmpgId=FRIP&menuId=002002`를 실제 파서(`parse_policy_all`)로 파싱해 DB와 대조:

| 비교 | 결과 |
| --- | --- |
| 라이브(현재) | 172행, `6주수요일 116 / 익월말 55 / 상세정책 0` — **깨끗** |
| 저장 raw(6-08) | 171행, 분포 동일. **라이브와 차이 단 2건**(와룡·방화동 6주수요일→익월말) + 진부령 1곳 추가 → **소스 안정적** |
| **DB `reservation_policies`** | 185행, `6주수요일 113 / 익월말 54 / **상세정책 18**` — **라이브·저장raw 어느 쪽과도 불일치** |

**핵심: 불일치는 staleness가 아니라 DB 적재 이력 문제.** DB의 `상세정책` 18곳 정체:
- **4곳**(광양백운산·여수봉황산·금산산림문화타운·통고산): FRIP 표에 구체값 존재 → DB가 틀림. **재파싱으로 교정.**
- **14곳**(대봉캠핑랜드·강원숲체험장·야영장·레포츠파크류): **비FRIP 공립시설**(국립 예약정책표에 없음). 레거시 placeholder.

**설계 반영(신규 결정):**
1. **선행 작업(Phase 0)**: `jforest crawl policies`(또는 저장 raw로 `reparse`) 실행해 `reservation_policies` 리프레시 → FRIP 171곳이 `6주수요일/익월말`로 정합, `상세정책` 사실상 소멸.
2. **`fcfs_report`의 `상세정책` 분기**는 리프레시 후 FRIP 대상엔 불필요 → **방어적 폴백으로만 유지**(제거하지 않되 의존하지 않음).
3. **비FRIP 14곳**은 국립 선착순/추첨/지역주민 정책이 없음 → 리포트에서 `정책 정보없음(비국립)`으로 표기하거나 제외(공립 자체 예약은 out-of-scope). `build_open_events`는 이들을 이벤트로 만들지 않음.
4. 리프레시 주기: 소스가 안정적이므로 저빈도(월 1회) 재크롤 + 변경 감시로 충분.

## 8. 리뷰로 확정된 결함 수정 요약 (2026-07-01)
| # | 결함 | 수정 |
| --- | --- | --- |
| 1 | title 키워드 분류 시 `104 지역주민우대추첨제` 오분류(추첨↔지역주민) | **rule_id 기반 분류**로 전환(§3.1) |
| 2 | `211 다자녀` 우선예약/추첨 혼재·자격제한인데 스코프 유입 | **211 전체 제외**(§3.1) |
| 3 | 선착순 시각 상수 가정("국립=오전9시")이 공립 22곳서 결측 | `open_time=None`+`time_confidence`(§3.2, §3.3) |
| 4 | 같은날 다중채널 중복(53곳) 미처리 | `(instt_id,group,open_time)` **병합 규칙**(§3.2b) |
| 5 | `reservable_label` 선착순 전용 로직 | **type_group별 라벨 표**(§3.2b) |
| 6 | 파싱 앵커 고정 120자 창이 뒤 섹션 날짜 오탐 | **섹션 경계 절단**(§3.2) |
| 7 | KST/ro 연결 미명세 | `ZoneInfo("Asia/Seoul")` + `mode=ro` URI(§3.5) |

---

## 9. 일일 갱신(Daily Refresh) 설계

### 9.1 무엇을 얼마나 자주 갱신하나 (데이터별 주기)
| 데이터 | 소스 | 주기 | 근거 |
| --- | --- | --- | --- |
| 공지(공사/예약제외/휴관) → `reservation_blocks` | notices 증분 크롤 + LLM | **매일 1회** | 매일 신규 공지 발생 |
| 예약정책 `reservation_policies` | FRIP 정책표 재크롤 | **월 1회**(+변경감시) | 소스 안정적(§7b: 한 달 새 2건) |
| 시설 `forest_facilities` | 정보페이지 + LLM | **분기/온디맨드** | 거의 불변 |
| 객실/가격 | rooms/prices 크롤 | 월 1회 | 시즌 전환 시 |

핵심: **매일 도는 건 공지→예약불가 파이프라인 하나**. 정책·시설은 저빈도. 그래서 데일리 잡은 가볍고 실패 위험이 낮다.

### 9.2 갱신 명령 (idempotent 합성 CLI)
```
jforest refresh-daily          # ① notices --incremental  ② alerts-extract
jforest refresh-monthly        # crawl policies + reparse + facilities
```
- 각 단계 **증분·멱등**(재실행 안전). `crawl notices`는 기존 twbbs_id skip(§4.2), `alerts-extract`는 미처리 공지만.
- **락파일**로 중복 실행 방지(`data/.refresh.lock`), 종료코드/로그 남김, 부분 실패해도 다음날 복구.
- **SQLite 안전**: DB를 `PRAGMA journal_mode=WAL`로 두면 데일리 잡(writer)과 웹(reader, `mode=ro`)이 **동시 동작 무충돌**.

### 9.3 스케줄링 방식 — 선택지와 결정

**결정: 프로덕션은 OS 스케줄러 → `jforest` CLI. "파이썬 인프로세스"가 필요하면 APScheduler.**

**(A) systemd timer (리눅스 서버, 권장)** — cron보다 현대적(로깅·의존성·재시도 내장):
```ini
# /etc/systemd/system/jforest-refresh.service
[Service]
Type=oneshot
WorkingDirectory=/srv/jforest
ExecStart=/srv/jforest/.venv/bin/jforest refresh-daily
# /etc/systemd/system/jforest-refresh.timer
[Timer]
OnCalendar=*-*-* 04:00:00
Persistent=true          # 꺼져있던 시간 놓친 실행 보정
[Install]
WantedBy=timers.target
```

**(B) cron (범용)**:
```cron
0 4 * * * cd /srv/jforest && .venv/bin/jforest refresh-daily >> data/refresh.log 2>&1
```

**(C) macOS 개발기 = launchd**(mac엔 cron 대신 네이티브):
`~/Library/LaunchAgents/ai.jforest.refresh.plist`에 `StartCalendarInterval{Hour=4}` + `ProgramArguments=[.venv/bin/jforest, refresh-daily]`.

**(D) 파이썬 인프로세스 cron = APScheduler** (FastAPI와 한 프로세스로 돌리고 싶을 때):
```python
# pyproject 의존성 추가: "apscheduler>=3.10"
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

@asynccontextmanager
async def lifespan(app):
    sched = AsyncIOScheduler(timezone="Asia/Seoul")
    sched.add_job(run_refresh_daily, CronTrigger(hour=4, minute=0),
                  id="daily", max_instances=1, coalesce=True, misfire_grace_time=3600)
    sched.start()
    yield
    sched.shutdown(wait=False)
# create_app(lifespan=lifespan). 크롤은 블로킹 → await run_in_threadpool(...)로 이벤트루프 보호.
```
⚠ 인프로세스 주의점: **uvicorn 단일 워커**(`--workers 1`)여야 중복 실행 안 됨(멀티워커면 워커마다 잡 발화). 웹 프로세스가 죽으면 잡도 멈춤 → 가용성이 웹에 묶임. 그래서 **운영 신뢰성은 (A)/(B)/(C)가 우위**, (D)는 "단일 인스턴스·올인원 배포" 편의용.

**경량 대안 `schedule`**: `schedule.every().day.at("04:00").do(...)` — 별도 스레드/프로세스에서 블로킹 루프. 영속성·misfire 처리 없음 → 이 앱엔 APScheduler 권장.

### 9.4 신선도 모니터링
- `fetch_log`에 마지막 성공시각 기록 → 웹 헤더에 "최종 갱신: N시간 전" 노출.
- 데일리 잡 실패 시 로그/알림(선택: 실패 카운트 임계 초과 시 웹에 "데이터 지연 중" 배너).

---

## 10. Vercel 배포 설계 (결정: 정적 스냅샷 + 로컬 launchd)

### 10.1 제약과 대응
| Vercel 제약 | 충돌 지점 | 대응 |
| --- | --- | --- |
| 무상태·읽기전용 FS(+/tmp), 로컬 파일 못 씀 | 1.3GB `jforest.db` 번들 불가 | **서빙 스냅샷** 4테이블만 → `api/serving.sqlite` **1.98MB**(실측) |
| 함수 번들 250MB | `api.py`가 `jforest.rag`→torch/qdrant(800MB+) 유입 | **import 격리**: 함수는 `fcfs_report`(re/datetime만)만 import. `.vercelignore`로 rag/embeddings/vector_index 제외. 실증: fcfs_report import 시 heavy 모듈 0개 |
| 장기 실행/데몬 불가 | 인프로세스 APScheduler·크롤 불가 | 데일리 파이프라인은 **Vercel 밖(로컬 맥 launchd)**. Vercel은 순수 읽기·계산만 |
| 실행시간 한도 | — | 리포트 계산은 2MB in-memory 조회라 <100ms. `maxDuration:15s` 여유 |

### 10.2 데이터 흐름
```
[로컬 맥] jforest.db(1.3GB)
  └ launchd 04:00 → refresh-daily(Phase2) → jforest export-serving → api/serving.sqlite(2MB)
                  → git push ─────────────▶ [Vercel] 자동 재배포
                                              api/index.py(ASGI) ← api/serving.sqlite(ro)
                                              build_open_events(date) 계산 → /open, /api/open-report
```
갱신 주기 = git push 시점(일 1회). 스냅샷 무변경이면 push 스킵(재배포 없음).

### 10.3 생성한 준비물 (구현·검증 완료)
| 파일 | 역할 | 상태 |
| --- | --- | --- |
| `jforest/export_serving.py` | 4(+reservation_blocks)테이블 → 2MB 스냅샷, `serving_meta.generated_at` 스탬프, VACUUM | ✅ 동작(1.98MB) |
| `jforest/cli.py :: export-serving` | `jforest export-serving --out` | ✅ |
| `api/index.py` | Vercel ASGI 진입점(경량). 현재 `/api/health`+placeholder | ✅ 로컬 검증 |
| `api/requirements.txt` | 함수 의존성 = `fastapi`만(torch 금지 주석) | ✅ |
| `vercel.json` | 전 경로 → `api/index`, mem 512·maxDuration 15 | ✅ |
| `.vercelignore` | data/·.venv/·무거운 서브모듈 제외(serving.sqlite는 유지) | ✅ |
| `deploy/refresh_and_publish.sh` | export→변경시 자동 commit/push, 락파일 | ✅ |
| `deploy/com.jforest.refresh.plist` | 매일 04:00 launchd | ✅ 템플릿 |
| `deploy/README.md` | 배포·갱신 런북 | ✅ |

### 10.4 Phase 1에서 `api/index.py` 교체 계약
health 스켈레톤을 아래로 확장(설계 §3.5/§3.6 그대로, 단 conn=serving.sqlite):
```python
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))  # jforest 패키지 인식
from jforest.fcfs_report import build_open_events, format_open_report  # Phase 1 산출
# GET /api/open-report?date= : _conn(serving.sqlite) → build_open_events(conn, date) → JSON(§3.5 스키마)
# GET /open                  : 날짜선택 HTML(§3.6, 반응형)
# serving_meta.generated_at  → 헤더 '최종 갱신' 표기
```
⚠ `build_open_events`는 **conn을 인자로 받으므로**(원본/스냅샷 무관) 로직 재사용에 수정 불필요.

### 10.5 대안(전환 지점)
- 재배포 없이 실시간 갱신 필요 → **Turso**(libSQL): `_conn()`만 libsql 클라이언트로 교체, 로직 그대로.
- git 히스토리 팽창 → 스냅샷을 **Vercel Blob**로 옮기고 콜드스타트 시 `/tmp`로 다운로드.
- 맥 상시성 부족 → 파이프라인을 **GitHub Actions/VM**으로 이전(§9.3).
