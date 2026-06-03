# 숲나들e 자연휴양림 크롤러 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 숲나들e(foresttrip.go.kr)에서 전국 자연휴양림의 기본정보·객실/가격·할인/예약정책·공지사항을 수집해 SQLite에 적재하는 Python CLI를 만든다.

**Architecture:** 단계별 파이프라인 CLI. 각 crawler가 HTTP로 받은 raw 응답을 `raw_pages`에 그대로 저장한 뒤, 네트워크를 모르는 순수 parser 함수로 구조화해 별도 테이블에 적재한다. fetch와 parse를 분리해 재요청 없이 `reparse`가 가능하다.

**Tech Stack:** Python 3.11+, uv(패키지), httpx(HTTP), selectolax(HTML 파싱), click(CLI), 표준 sqlite3(DB), pytest(테스트).

**참조 스펙:** `docs/superpowers/specs/2026-06-03-foresttrip-crawler-design.md`

---

## 파일 구조

| 파일 | 책임 |
| --- | --- |
| `pyproject.toml` | uv 패키지/의존성/스크립트 정의 |
| `jforest/__init__.py` | 패키지 마커 |
| `jforest/__main__.py` | `python -m jforest` 진입점 → `cli.main()` |
| `jforest/db.py` | SQLite 연결, 스키마 생성, `save_raw`, `get_raw_pages` |
| `jforest/http.py` | `Client`: 딜레이/재시도/UA, `fetch_log` 기록, `get()`/`download()` |
| `jforest/parsers/forests.py` | JSON 목록 파서 + HTML 목록 파서 (순수) |
| `jforest/parsers/rooms.py` | 객실 목록 파서 (순수) |
| `jforest/parsers/room_details.py` | 객실 상세 파서 (순수) |
| `jforest/parsers/discounts.py` | 할인정책 파서 (순수) |
| `jforest/parsers/policies.py` | 예약정책 전체표/개별 파서 (순수) |
| `jforest/parsers/notices.py` | 공지 목록/상세 파서 (순수) |
| `jforest/crawlers/forests.py` | 1단계: 휴양림 목록 1a(JSON)+1b(HTML) |
| `jforest/crawlers/rooms.py` | 2단계: 객실 목록 |
| `jforest/crawlers/room_details.py` | 3단계: 객실 상세 |
| `jforest/crawlers/discounts.py` | 4단계: 할인정책 |
| `jforest/crawlers/policies.py` | 5단계: 예약정책 |
| `jforest/crawlers/notices.py` | 6단계: 공지 + 첨부 |
| `jforest/cli.py` | click 그룹: `crawl`, `reparse`, `status` |
| `tests/fixtures/*` | 실제 사이트 응답 샘플 |
| `tests/test_*.py` | parser 단위 + crawler 통합 테스트 |

모든 parser는 `parse_*(text: str) -> list[dict] | dict` 시그니처의 순수 함수다. 모든 crawler는 `run(conn, client, *, limit=None, force=False) -> Summary` 시그니처를 가진다.

---

## Task 0: 프로젝트 스캐폴딩

**Files:**
- Create: `pyproject.toml`
- Create: `jforest/__init__.py`
- Create: `jforest/__main__.py`
- Create: `jforest/parsers/__init__.py`
- Create: `jforest/crawlers/__init__.py`
- Create: `tests/__init__.py`
- Create: `.gitignore`

- [ ] **Step 1: pyproject.toml 작성**

```toml
[project]
name = "jforest"
version = "0.1.0"
description = "숲나들e 자연휴양림 크롤러"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",
    "selectolax>=0.3.21",
    "click>=8.1",
]

[project.scripts]
jforest = "jforest.cli:main"

[dependency-groups]
dev = ["pytest>=8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: 빈 패키지 파일 생성**

`jforest/__init__.py`, `jforest/parsers/__init__.py`, `jforest/crawlers/__init__.py`, `tests/__init__.py` 를 빈 파일로 생성한다.

`jforest/__main__.py`:

```python
from jforest.cli import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: .gitignore 작성**

```gitignore
__pycache__/
*.pyc
.venv/
data/
.pytest_cache/
```

- [ ] **Step 4: 의존성 설치 및 확인**

Run: `uv sync && uv run python -c "import httpx, selectolax, click; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git init 2>/dev/null; git add -A
git commit -m "chore: scaffold jforest crawler project"
```

> 참고: 이 저장소는 아직 git 저장소가 아닐 수 있다. `git init`을 먼저 실행한다.

---

## Task 1: DB 스키마와 raw 헬퍼 (`db.py`)

**Files:**
- Create: `jforest/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_db.py
import sqlite3
from jforest.db import init_db, save_raw, get_raw_pages

def test_init_db_creates_all_tables():
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert {"raw_pages", "forests", "rooms", "room_prices",
            "room_usage_texts", "discount_policies", "reservation_policies",
            "notices", "notice_attachments", "fetch_log"} <= names

def test_save_raw_is_idempotent_on_page_type_ref_key():
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    save_raw(conn, "http://x", "room_list", "ID1", 200, "<old/>", "2026-06-03T00:00:00")
    save_raw(conn, "http://x", "room_list", "ID1", 200, "<new/>", "2026-06-03T01:00:00")
    rows = list(conn.execute("SELECT body FROM raw_pages WHERE page_type='room_list' AND ref_key='ID1'"))
    assert len(rows) == 1
    assert rows[0][0] == "<new/>"

def test_get_raw_pages_filters_by_page_type():
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    save_raw(conn, "u1", "room_list", "A", 200, "a", "t")
    save_raw(conn, "u2", "discount", "B", 200, "b", "t")
    got = get_raw_pages(conn, "room_list")
    assert [r["ref_key"] for r in got] == ["A"]
    assert got[0]["body"] == "a"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jforest.db'`

- [ ] **Step 3: `db.py` 구현**

```python
# jforest/db.py
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_pages (
  id INTEGER PRIMARY KEY,
  url TEXT NOT NULL,
  page_type TEXT NOT NULL,
  ref_key TEXT NOT NULL,
  http_status INTEGER,
  body TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  UNIQUE (page_type, ref_key)
);
CREATE TABLE IF NOT EXISTS forests (
  instt_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  sido_code INTEGER,
  arcd TEXT,
  instt_type_code TEXT,
  instt_type TEXT,
  homepage_url TEXT,
  tags TEXT,
  summary TEXT,
  reservation_intake TEXT,
  fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rooms (
  goods_id TEXT PRIMARY KEY,
  instt_id TEXT NOT NULL,
  room_type TEXT,
  name TEXT,
  capacity_standard INTEGER,
  capacity_max INTEGER,
  area TEXT,
  fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS room_prices (
  id INTEGER PRIMARY KEY,
  goods_id TEXT NOT NULL,
  season TEXT NOT NULL,
  day_type TEXT NOT NULL,
  raw_label TEXT,
  price INTEGER NOT NULL,
  fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS room_usage_texts (
  goods_id TEXT PRIMARY KEY,
  checkin_time TEXT,
  checkout_time TEXT,
  amenities TEXT,
  usage_guide TEXT,
  fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS discount_policies (
  id INTEGER PRIMARY KEY,
  instt_id TEXT NOT NULL,
  target TEXT,
  category TEXT,
  timing TEXT,
  apply_date TEXT,
  room_rates TEXT,
  campsite_rate TEXT,
  facility_rate TEXT,
  fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reservation_policies (
  instt_id TEXT PRIMARY KEY,
  operates_rooms INTEGER,
  operates_campsite INTEGER,
  operates_waitlist INTEGER,
  fcfs_method TEXT,
  lottery_types TEXT,
  priority_types TEXT,
  fcfs_detail TEXT,
  lottery_detail TEXT,
  fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notices (
  instt_id TEXT NOT NULL,
  twbbs_id TEXT NOT NULL,
  title TEXT,
  updated_at TEXT,
  body_text TEXT,
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (instt_id, twbbs_id)
);
CREATE TABLE IF NOT EXISTS notice_attachments (
  id INTEGER PRIMARY KEY,
  instt_id TEXT NOT NULL,
  twbbs_id TEXT NOT NULL,
  file_master_id TEXT,
  file_id TEXT,
  file_name TEXT,
  content_type TEXT,
  local_path TEXT,
  downloaded INTEGER DEFAULT 0,
  fetched_at TEXT NOT NULL,
  UNIQUE (file_master_id, file_id)
);
CREATE TABLE IF NOT EXISTS fetch_log (
  id INTEGER PRIMARY KEY,
  url TEXT,
  http_status INTEGER,
  error TEXT,
  duration_ms INTEGER,
  fetched_at TEXT NOT NULL
);
"""


def get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def save_raw(conn, url, page_type, ref_key, http_status, body, fetched_at):
    conn.execute(
        "INSERT OR REPLACE INTO raw_pages "
        "(url, page_type, ref_key, http_status, body, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (url, page_type, ref_key, http_status, body, fetched_at),
    )
    conn.commit()


def get_raw_pages(conn, page_type) -> list:
    return list(conn.execute(
        "SELECT * FROM raw_pages WHERE page_type = ? ORDER BY ref_key",
        (page_type,),
    ))
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_db.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add jforest/db.py tests/test_db.py
git commit -m "feat: SQLite schema + raw_pages helpers"
```

---

## Task 2: HTTP 클라이언트 (`http.py`)

**Files:**
- Create: `jforest/http.py`
- Test: `tests/test_http.py`

`Client`는 `httpx.Client`를 감싸 요청 간 딜레이, 지수 백오프 재시도(3회), 고정 UA, `fetch_log` 기록을 담당한다. 테스트는 `transport`에 `httpx.MockTransport`를 주입해 네트워크 없이 검증한다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_http.py
import sqlite3
import httpx
from jforest.db import init_db
from jforest.http import Client

def make_client(handler, **kw):
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row
    init_db(conn)
    transport = httpx.MockTransport(handler)
    return conn, Client(conn, delay=0, transport=transport, **kw)

def test_get_returns_status_and_body_and_logs():
    def handler(request):
        return httpx.Response(200, text="hello")
    conn, c = make_client(handler)
    status, body = c.get("https://x/test")
    assert status == 200 and body == "hello"
    logs = list(conn.execute("SELECT url, http_status, error FROM fetch_log"))
    assert logs[0]["http_status"] == 200 and logs[0]["error"] is None

def test_get_retries_then_succeeds():
    calls = {"n": 0}
    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, text="ok")
    conn, c = make_client(handler, retries=3)
    status, body = c.get("https://x/retry")
    assert status == 200 and body == "ok" and calls["n"] == 3

def test_get_gives_up_after_retries_and_logs_error():
    def handler(request):
        return httpx.Response(500)
    conn, c = make_client(handler, retries=2)
    status, body = c.get("https://x/fail")
    assert status == 500
    err = list(conn.execute("SELECT error FROM fetch_log ORDER BY id DESC LIMIT 1"))[0]["error"]
    assert err is not None

def test_download_returns_bytes_and_headers():
    def handler(request):
        return httpx.Response(200, content=b"\xff\xd8\xff\x00", headers={"Content-Type": "image/jpeg"})
    conn, c = make_client(handler)
    status, content, headers = c.download("https://x/file")
    assert status == 200 and content[:3] == b"\xff\xd8\xff"
    assert headers["Content-Type"] == "image/jpeg"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_http.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jforest.http'`

- [ ] **Step 3: `http.py` 구현**

```python
# jforest/http.py
import time
from datetime import datetime, timezone

import httpx

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")
BASE = "https://www.foresttrip.go.kr"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Client:
    def __init__(self, conn, delay=1.0, retries=3, timeout=30.0, transport=None):
        self.conn = conn
        self.delay = delay
        self.retries = retries
        self._client = httpx.Client(
            headers={"User-Agent": UA},
            timeout=timeout,
            transport=transport,
            follow_redirects=True,
        )

    def _backoff(self, attempt):
        # 백오프도 delay에 비례시킨다 → delay=0(테스트)이면 sleep 없음, 실제 수집은 1·2·4초…
        if self.delay:
            time.sleep(self.delay * min(2 ** attempt, 10))

    def _log(self, url, status, error, duration_ms):
        self.conn.execute(
            "INSERT INTO fetch_log (url, http_status, error, duration_ms, fetched_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (url, status, error, duration_ms, _now()),
        )
        self.conn.commit()

    def _request(self, method, url, **kw):
        last_status, last_error = None, None
        for attempt in range(1, self.retries + 1):
            if self.delay:
                time.sleep(self.delay)
            start = time.monotonic()
            try:
                resp = self._client.request(method, url, **kw)
                dur = int((time.monotonic() - start) * 1000)
                if resp.status_code >= 500:
                    last_status, last_error = resp.status_code, f"HTTP {resp.status_code}"
                    self._log(url, resp.status_code, f"retry {attempt}: HTTP {resp.status_code}", dur)
                    self._backoff(attempt)
                    continue
                self._log(url, resp.status_code, None, dur)
                return resp
            except httpx.HTTPError as e:
                dur = int((time.monotonic() - start) * 1000)
                last_status, last_error = None, str(e)
                self._log(url, None, f"retry {attempt}: {e}", dur)
                self._backoff(attempt)
        # 모든 재시도 실패 → 마지막 에러를 별도 기록
        self._log(url, last_status, f"gave up after {self.retries} retries: {last_error}", 0)
        return httpx.Response(last_status or 599, text="")

    def get(self, url, params=None):
        resp = self._request("GET", url, params=params)
        return resp.status_code, resp.text

    def download(self, url, params=None):
        resp = self._request("GET", url, params=params)
        return resp.status_code, resp.content, resp.headers
```

> 주의: `test_get_gives_up_after_retries_and_logs_error`는 항상 500을 반환하므로 마지막에 `gave up...` 로그가 남는다. `Response(500)`이 반환된다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_http.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add jforest/http.py tests/test_http.py
git commit -m "feat: HTTP client with retry/delay/fetch_log"
```

---

## Task 3: 실제 응답 fixture 수집

**Files:**
- Create: `tests/fixtures/forest_list_sido1.json`
- Create: `tests/fixtures/forest_list_html_p1.html`
- Create: `tests/fixtures/room_list.html`
- Create: `tests/fixtures/room_detail.html`
- Create: `tests/fixtures/discount.html`
- Create: `tests/fixtures/policy_all.html`
- Create: `tests/fixtures/policy_detail.html`
- Create: `tests/fixtures/notice_list.html`
- Create: `tests/fixtures/notice_detail.html`

이후 parser 테스트가 의존하는 실제 응답을 한 번만 내려받아 저장한다. 네트워크 일시 사용(수집 단계가 아닌 fixture 준비).

- [ ] **Step 1: fixture 다운로드 스크립트 실행**

Run:
```bash
mkdir -p tests/fixtures
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
B="https://www.foresttrip.go.kr"
curl -s -A "$UA" "$B/pot/rm/cs/selectInsttHuyangList.do?srchSido=1" -o tests/fixtures/forest_list_sido1.json
curl -s -A "$UA" "$B/pot/is/fs/selectFcltSrchView.do?hmpgId=FRIP&menuId=002001" -o tests/fixtures/forest_list_html_p1.html
curl -s -A "$UA" "$B/pot/rm/fa/selectFcltsArmpListView.do?hmpgId=ID02030124&menuId=002002001" -o tests/fixtures/room_list.html
curl -s -A "$UA" "$B/pot/rm/fa/selectFcltsArmpDtlView.do?insttId=ID02030124&goodsId=GID020301240100101001001000004" -o tests/fixtures/room_detail.html
curl -s -A "$UA" "$B/pot/rm/ug/selectDcPolicyView.do?hmpgId=FRIP&menuId=002004&insttId=0113" -o tests/fixtures/discount.html
curl -s -A "$UA" "$B/pot/cc/bb/selectFripRsrvtPolcyView.do?hmpgId=FRIP&menuId=002002" -o tests/fixtures/policy_all.html
curl -s -A "$UA" "$B/pot/rm/ug/selectRsrvtGdncView.do?hmpgId=0113&menuId=004001001&ruleId=101" -o tests/fixtures/policy_detail.html
curl -s -A "$UA" "$B/pot/cc/nm/selectNticBbrssListView.do?hmpgId=0113&menuId=005001&bbrssMsterId=BBRSSMSTER_00000051" -o tests/fixtures/notice_list.html
curl -s -A "$UA" "$B/pot/cc/nm/selectNticBbrssDtlView.do?hmpgId=0113&menuId=005001&twbbsId=250396&bbrssMsterId=BBRSSMSTER_00000051" -o tests/fixtures/notice_detail.html
```

- [ ] **Step 2: 다운로드 검증**

Run: `for f in tests/fixtures/*; do echo "$f: $(wc -c < "$f") bytes"; done`
Expected: 모든 파일이 1000바이트 이상. `room_list.html`에 `GID020301240100101001001000004`, `notice_list.html`에 `var totPage`가 포함되어야 한다:

Run: `grep -c "GID020301240100101001001000004" tests/fixtures/room_list.html && grep -c "totPage" tests/fixtures/notice_list.html`
Expected: 둘 다 1 이상

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures
git commit -m "test: capture live response fixtures"
```

> 참고: 공지 목록 같은 동적 페이지는 시간이 지나면 내용이 바뀐다. 테스트는 구조(필드 존재/형식)와 알려진 안정 값(예: `twbbsId=250396` 행, `totPage` 숫자형)을 검증하며, 회차별로 바뀌는 목록 항목 수에는 의존하지 않는다.

---

## Task 4: 휴양림 목록 parser (`parsers/forests.py`)

**Files:**
- Create: `jforest/parsers/forests.py`
- Test: `tests/test_parser_forests.py`

JSON 목록은 `insttId/insttNm/arcd/insttTpcd`만 반환한다.

**HTML 목록 구조 (라이브 검증):** 항목 데이터는 서버 렌더 DOM이 아니라 `<script>` 안 `var positions = [ {content : '<...JS 문자열...>'}, ... ]` 배열에 들어 있다(페이지당 4곳). 각 `content` 문자열은 다음을 포함한다:
- `<input type="hidden" id="ID02030002">` → instt_id (숫자형 `0113`도 가능)
- `<div class="info_title">…가리산 자연휴양림</div>` → 이름
- `<div class="info_button"><a href="https://garisan.foresttrip.go.kr" …><span>홈페이지</span></a>` → **실제 홈페이지 URL**
- `<li class="icon_01"> 주소</li>`, `<li class="icon_02"> 전화</li>`

따라서 DOM 셀렉터가 아니라 **JS 문자열을 정규식으로 추출**한다. `instt_type`(라벨)·`summary`·`reservation_intake`는 이 뷰에 신뢰 가능한 형태로 없으므로 `None`으로 둔다(각각 `instt_type_code`(1a), 후속, `reservation_policies`로 보강).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_parser_forests.py
from pathlib import Path
from jforest.parsers.forests import parse_forest_list_json, parse_forest_list_html

FX = Path(__file__).parent / "fixtures"

def test_parse_json_returns_id_name_arcd_typecode():
    rows = parse_forest_list_json((FX / "forest_list_sido1.json").read_text(encoding="utf-8"))
    assert len(rows) >= 20
    sample = rows[0]
    assert set(sample) == {"instt_id", "name", "arcd", "instt_type_code"}
    assert all(r["instt_id"] for r in rows)

def test_parse_json_contains_known_forest():
    rows = parse_forest_list_json((FX / "forest_list_sido1.json").read_text(encoding="utf-8"))
    ids = {r["instt_id"] for r in rows}
    assert "ID02030019" in ids  # 강씨봉

def test_parse_html_extracts_items_from_js_positions():
    items = parse_forest_list_html((FX / "forest_list_html_p1.html").read_text(encoding="utf-8"))
    # 페이지당 4곳
    assert len(items) == 4
    by_id = {it["instt_id"]: it for it in items}
    assert "ID02030002" in by_id  # 가리산
    it = by_id["ID02030002"]
    assert "가리산" in (it["name"] or "")
    assert it["homepage_url"] == "https://garisan.foresttrip.go.kr"
    # 미보강 필드는 None
    assert it["instt_type"] is None and it["summary"] is None

def test_parse_html_handles_numeric_id():
    items = parse_forest_list_html((FX / "forest_list_html_p1.html").read_text(encoding="utf-8"))
    assert "0113" in {it["instt_id"] for it in items}  # 가리왕산(숫자형 id)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_parser_forests.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: `parsers/forests.py` 구현**

```python
# jforest/parsers/forests.py
import json
import re


def parse_forest_list_json(text: str) -> list[dict]:
    data = json.loads(text)
    # 응답은 리스트이거나 {"list": [...]} 형태일 수 있다. 둘 다 수용.
    if isinstance(data, dict):
        for key in ("list", "resultList", "data", "huyangList"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    rows = []
    for item in data:
        instt_id = item.get("insttId")
        if not instt_id:
            continue
        rows.append({
            "instt_id": instt_id,
            "name": item.get("insttNm"),
            "arcd": item.get("arcd"),
            "instt_type_code": item.get("insttTpcd"),
        })
    return rows


# 각 항목 content 문자열의 시작 마커 / 필드 정규식
_ITEM = re.compile(r'<div class="map_info" id="site\d+"')
_IID = re.compile(r'<input type="hidden" id="([A-Za-z0-9]+)">')
_NAME = re.compile(r"info_title\">.*?([^'<>+]+?)</div>", re.S)
_HOME = re.compile(r'class="info_button">.*?<a href="([^"]+)"[^>]*>\s*<span>홈페이지', re.S)


def parse_forest_list_html(text: str) -> list[dict]:
    # 항목 데이터는 <script> 안 `var positions = [ {content:'...'} ]` 배열에 있다.
    m = re.search(r"var\s+positions\s*=\s*\[(.*?)\];", text, re.S)
    region = m.group(1) if m else text
    starts = [mm.start() for mm in _ITEM.finditer(region)]
    items = []
    for i, s in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(region)
        block = region[s:end]
        iid_m = _IID.search(block)
        if not iid_m:
            continue
        name_m = _NAME.search(block)
        name = re.sub(r"\s+", " ", name_m.group(1)).strip() if name_m else None
        home_m = _HOME.search(block)
        tags = re.findall(r"#[가-힣A-Za-z0-9]+", block)
        items.append({
            "instt_id": iid_m.group(1),
            "name": name or None,
            "instt_type": None,            # HTML에 기관구분 라벨 없음 → 1a의 instt_type_code 사용
            "homepage_url": home_m.group(1) if home_m else None,
            "tags": json.dumps(tags, ensure_ascii=False) if tags else None,
            "summary": None,               # 이 뷰에 요약 없음
            "reservation_intake": None,    # reservation_policies로 보강
        })
    return items
```

> 설계 주: 핵심 데이터(id/이름/지역/유형코드)는 JSON(1a)에서 확보되므로 1b 파싱이 일부 비어도 파이프라인은 동작한다. 1b는 `homepage_url`/`tags` 보강이 주목적이다. 이 모듈은 정규식만 사용하므로 `selectolax`를 import하지 않는다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_parser_forests.py -v`
Expected: PASS (4 passed). 항목 수가 4가 아니면(사이트가 페이지당 항목 수를 변경한 경우) 아래 디버그로 블록 수를 확인한다.

Debug(필요 시): `uv run python -c "import re; h=open('tests/fixtures/forest_list_html_p1.html',encoding='utf-8').read(); print(len(re.findall(r'map_info\" id=\"site', h)))"`

- [ ] **Step 5: Commit**

```bash
git add jforest/parsers/forests.py tests/test_parser_forests.py
git commit -m "feat: forest list parsers (json + html)"
```

---

## Task 5: 휴양림 목록 crawler (`crawlers/forests.py`)

**Files:**
- Create: `jforest/crawlers/forests.py`
- Create: `jforest/util.py` (공통 `now_iso`, `Summary`)
- Test: `tests/test_crawler_forests.py`

- [ ] **Step 1: 공통 유틸 작성**

```python
# jforest/util.py
from dataclasses import dataclass, field
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Summary:
    ok: int = 0
    skipped: int = 0
    failed: int = 0
    failures: list = field(default_factory=list)

    def line(self) -> str:
        return f"성공 {self.ok}건 / 건너뜀 {self.skipped}건 / 실패 {self.failed}건"
```

- [ ] **Step 2: 실패하는 테스트 작성**

```python
# tests/test_crawler_forests.py
import sqlite3
import httpx
from pathlib import Path
from jforest.db import init_db
from jforest.http import Client
from jforest.crawlers.forests import run

FX = Path(__file__).parent / "fixtures"

def build(handler):
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn, Client(conn, delay=0, transport=httpx.MockTransport(handler))

def test_run_populates_forests_from_json_and_saves_raw():
    json_body = (FX / "forest_list_sido1.json").read_text(encoding="utf-8")
    html_body = (FX / "forest_list_html_p1.html").read_text(encoding="utf-8")
    def handler(request):
        if "selectInsttHuyangList" in request.url.path:
            # sido=1만 데이터, 2~9는 빈 목록
            if request.url.params.get("srchSido") == "1":
                return httpx.Response(200, text=json_body)
            return httpx.Response(200, text="[]")
        if "selectFcltSrchView" in request.url.path:
            return httpx.Response(200, text=html_body)
        if "selectMenuList" in request.url.path:
            return httpx.Response(200, text='{"list":[]}')
        return httpx.Response(404)
    conn, client = build(handler)
    summary = run(conn, client)
    n = conn.execute("SELECT COUNT(*) FROM forests").fetchone()[0]
    assert n >= 20
    raw = conn.execute("SELECT COUNT(*) FROM raw_pages WHERE page_type='forest_list_json'").fetchone()[0]
    assert raw == 9  # sido 1..9
    assert summary.ok >= 20
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `uv run pytest tests/test_crawler_forests.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: `crawlers/forests.py` 구현**

```python
# jforest/crawlers/forests.py
from jforest.http import BASE
from jforest.db import save_raw
from jforest.parsers.forests import parse_forest_list_json, parse_forest_list_html
from jforest.util import now_iso, Summary

JSON_URL = f"{BASE}/pot/rm/cs/selectInsttHuyangList.do"
HTML_URL = f"{BASE}/pot/is/fs/selectFcltSrchView.do"
MENU_URL = f"{BASE}/com/sub/selectMenuList.do"


def run(conn, client, *, limit=None, force=False) -> Summary:
    s = Summary()
    # --- 1a: 지역별 JSON ---
    for sido in range(1, 10):
        status, body = client.get(JSON_URL, params={"srchSido": sido})
        save_raw(conn, JSON_URL, "forest_list_json", str(sido), status, body, now_iso())
        if status != 200:
            s.failed += 1; s.failures.append(f"sido={sido} HTTP {status}"); continue
        try:
            rows = parse_forest_list_json(body)
        except Exception as e:
            s.failed += 1; s.failures.append(f"sido={sido} parse: {e}"); continue
        for r in rows:
            conn.execute(
                "INSERT OR REPLACE INTO forests "
                "(instt_id, name, sido_code, arcd, instt_type_code, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (r["instt_id"], r["name"], sido, r["arcd"], r["instt_type_code"], now_iso()),
            )
            s.ok += 1
        conn.commit()
        if limit and s.ok >= limit:
            break

    # --- 1b: HTML 목록 전체 페이지 보강 ---
    page = 1
    tot_page = 1
    while page <= tot_page:
        status, body = client.get(HTML_URL, params={"hmpgId": "FRIP", "menuId": "002001", "nowPage": page})
        save_raw(conn, HTML_URL, "forest_list_html", str(page), status, body, now_iso())
        if status != 200:
            break
        if page == 1:
            tot_page = _find_tot_page(body)
        for it in parse_forest_list_html(body):
            conn.execute(
                "UPDATE forests SET instt_type=COALESCE(?, instt_type), "
                "homepage_url=COALESCE(?, homepage_url), tags=COALESCE(?, tags), "
                "summary=COALESCE(?, summary), reservation_intake=COALESCE(?, reservation_intake) "
                "WHERE instt_id=?",
                (it["instt_type"], it["homepage_url"], it["tags"], it["summary"],
                 it["reservation_intake"], it["instt_id"]),
            )
        conn.commit()
        page += 1
        if limit:
            break  # 스모크 모드에서는 1페이지만

    # --- 검증: insttId == hmpgId (표본) ---
    _assert_hmpgid(conn, client)
    return s


def _find_tot_page(body: str) -> int:
    import re
    m = re.search(r"var\s+totPage\s*=\s*(\d+)", body)
    return int(m.group(1)) if m else 1


def _assert_hmpgid(conn, client):
    import json as _json
    row = conn.execute("SELECT instt_id FROM forests LIMIT 1").fetchone()
    if not row:
        return
    iid = row["instt_id"]
    status, body = client.get(MENU_URL, params={"hmpgId": iid})
    # 메뉴 응답이 200이면 insttId가 hmpgId로 동작한다고 간주.
    if status != 200:
        raise AssertionError(
            f"insttId==hmpgId 검증 실패: hmpgId={iid} 메뉴 호출 HTTP {status}. URL 매핑을 재확인하라."
        )
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/test_crawler_forests.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add jforest/crawlers/forests.py jforest/util.py tests/test_crawler_forests.py
git commit -m "feat: forests crawler (1a json + 1b html enrich + hmpgId assert)"
```

---

## Task 6: 객실 목록 parser (`parsers/rooms.py`)

**Files:**
- Create: `jforest/parsers/rooms.py`
- Test: `tests/test_parser_rooms.py`

실제 구조(검증): `<tr class="mapListTr" id="tr_GID...">` / `td[0]`=유형 / `td[1] data-title="시설물명"`=이름 / `td[2] data-title="최대인원/면적"`="3인실, 20㎡" / `td[3]` 상세링크.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_parser_rooms.py
from pathlib import Path
from jforest.parsers.rooms import parse_room_list

FX = Path(__file__).parent / "fixtures"

def test_parse_room_list_extracts_known_room():
    rooms = parse_room_list((FX / "room_list.html").read_text(encoding="utf-8"))
    by_id = {r["goods_id"]: r for r in rooms}
    r = by_id["GID020301240100101001001000004"]
    assert r["room_type"] == "숲속의집"
    assert r["name"] == "A동-101호(거류산)"
    assert r["capacity_max"] == 3
    assert "20" in r["area"]

def test_parse_room_list_all_have_goods_id():
    rooms = parse_room_list((FX / "room_list.html").read_text(encoding="utf-8"))
    assert len(rooms) >= 1
    assert all(r["goods_id"].startswith("GID") for r in rooms)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_parser_rooms.py -v`
Expected: FAIL

- [ ] **Step 3: `parsers/rooms.py` 구현**

```python
# jforest/parsers/rooms.py
import re

from selectolax.parser import HTMLParser


def parse_room_list(text: str) -> list[dict]:
    tree = HTMLParser(text)
    rooms = []
    for tr in tree.css("tr.mapListTr"):
        tr_id = tr.attributes.get("id") or ""
        m = re.search(r"GID[0-9A-Za-z]+", tr_id)
        if not m:
            inner = tr.html or ""
            m = re.search(r"goodsId=(GID[0-9A-Za-z]+)", inner)
        if not m:
            continue
        goods_id = m.group(0).replace("goodsId=", "")
        tds = tr.css("td")
        room_type = tds[0].text(strip=True) if len(tds) > 0 else None
        name = tds[1].text(strip=True) if len(tds) > 1 else None
        capacity_area = tds[2].text(strip=True) if len(tds) > 2 else ""
        cap_m = re.search(r"(\d+)\s*인", capacity_area)
        area_m = re.search(r"([\d.]+\s*㎡)", capacity_area)
        rooms.append({
            "goods_id": goods_id,
            "room_type": room_type,
            "name": name,
            "capacity_standard": None,  # 목록에는 없음. 상세에서 보강
            "capacity_max": int(cap_m.group(1)) if cap_m else None,
            "area": area_m.group(1) if area_m else (capacity_area or None),
        })
    return rooms
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_parser_rooms.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add jforest/parsers/rooms.py tests/test_parser_rooms.py
git commit -m "feat: room list parser"
```

---

## Task 7: 객실 목록 crawler (`crawlers/rooms.py`)

**Files:**
- Create: `jforest/crawlers/rooms.py`
- Test: `tests/test_crawler_rooms.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_crawler_rooms.py
import sqlite3, httpx
from pathlib import Path
from jforest.db import init_db
from jforest.http import Client
from jforest.crawlers.rooms import run
from jforest.util import now_iso

FX = Path(__file__).parent / "fixtures"

def seed_forest(conn, iid):
    conn.execute("INSERT INTO forests (instt_id, name, fetched_at) VALUES (?,?,?)",
                 (iid, "테스트휴양림", now_iso())); conn.commit()

def test_run_inserts_rooms_for_each_forest():
    body = (FX / "room_list.html").read_text(encoding="utf-8")
    def handler(request):
        return httpx.Response(200, text=body)
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    seed_forest(conn, "ID02030124")
    client = Client(conn, delay=0, transport=httpx.MockTransport(handler))
    summary = run(conn, client)
    n = conn.execute("SELECT COUNT(*) FROM rooms WHERE instt_id='ID02030124'").fetchone()[0]
    assert n >= 1
    assert summary.ok >= 1

def test_run_skips_already_collected_unless_force():
    body = (FX / "room_list.html").read_text(encoding="utf-8")
    def handler(request):
        return httpx.Response(200, text=body)
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    seed_forest(conn, "ID02030124")
    client = Client(conn, delay=0, transport=httpx.MockTransport(handler))
    run(conn, client)
    s2 = run(conn, client)  # 두 번째는 건너뜀
    assert s2.skipped >= 1 and s2.ok == 0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_crawler_rooms.py -v`
Expected: FAIL

- [ ] **Step 3: `crawlers/rooms.py` 구현**

```python
# jforest/crawlers/rooms.py
from jforest.http import BASE
from jforest.db import save_raw
from jforest.parsers.rooms import parse_room_list
from jforest.util import now_iso, Summary

LIST_URL = f"{BASE}/pot/rm/fa/selectFcltsArmpListView.do"


def run(conn, client, *, limit=None, force=False) -> Summary:
    s = Summary()
    forests = list(conn.execute("SELECT instt_id FROM forests ORDER BY instt_id"))
    if limit:
        forests = forests[:limit]
    for f in forests:
        iid = f["instt_id"]
        if not force:
            existing = conn.execute(
                "SELECT 1 FROM raw_pages WHERE page_type='room_list' AND ref_key=?", (iid,)
            ).fetchone()
            if existing:
                s.skipped += 1
                continue
        status, body = client.get(LIST_URL, params={"hmpgId": iid, "menuId": "002002001"})
        save_raw(conn, LIST_URL, "room_list", iid, status, body, now_iso())
        if status != 200:
            s.failed += 1; s.failures.append(f"{iid} HTTP {status}"); continue
        try:
            rooms = parse_room_list(body)
        except Exception as e:
            s.failed += 1; s.failures.append(f"{iid} parse: {e}"); continue
        if not rooms:
            # 객실 미운영 휴양림: 정상 케이스로 fetch_log에 not_available 기록
            conn.execute(
                "INSERT INTO fetch_log (url, http_status, error, duration_ms, fetched_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (LIST_URL, status, "not_available", 0, now_iso()),
            )
            conn.commit()
            s.skipped += 1
            continue
        for r in rooms:
            conn.execute(
                "INSERT OR REPLACE INTO rooms "
                "(goods_id, instt_id, room_type, name, capacity_standard, capacity_max, area, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (r["goods_id"], iid, r["room_type"], r["name"],
                 r["capacity_standard"], r["capacity_max"], r["area"], now_iso()),
            )
        conn.commit()
        s.ok += 1
    return s
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_crawler_rooms.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add jforest/crawlers/rooms.py tests/test_crawler_rooms.py
git commit -m "feat: rooms crawler with resume/force"
```

---

## Task 8: 객실 상세 parser (`parsers/room_details.py`)

**Files:**
- Create: `jforest/parsers/room_details.py`
- Test: `tests/test_parser_room_details.py`

실제 구조(검증): `인실/면적` 행 td = `기준인원 : 2 <br>최대인원 : 3 <br>면적 : 20㎡`; `편의시설` 행 td; 가격 tbody = `<th rowspan=2>비수기</th><td>평일요금 60,000원</td>`...; 이용안내 = `div.con_item > p.wd_txt` (입실/퇴실 시간이 본문 내 텍스트).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_parser_room_details.py
from pathlib import Path
from jforest.parsers.room_details import parse_room_detail

FX = Path(__file__).parent / "fixtures"

def test_parse_room_detail_capacity_and_area():
    d = parse_room_detail((FX / "room_detail.html").read_text(encoding="utf-8"))
    assert d["capacity_standard"] == 2
    assert d["capacity_max"] == 3
    assert "20" in d["area"]

def test_parse_room_detail_prices():
    d = parse_room_detail((FX / "room_detail.html").read_text(encoding="utf-8"))
    prices = {(p["season"], p["day_type"]): p["price"] for p in d["prices"]}
    assert prices[("off", "weekday")] == 60000
    assert prices[("off", "weekend")] == 80000
    assert prices[("peak", "weekday")] == 80000
    assert prices[("peak", "weekend")] == 80000

def test_parse_room_detail_texts():
    d = parse_room_detail((FX / "room_detail.html").read_text(encoding="utf-8"))
    assert "전자레인지" in (d["amenities"] or "")
    assert d["usage_guide"] and len(d["usage_guide"]) > 20
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_parser_room_details.py -v`
Expected: FAIL

- [ ] **Step 3: `parsers/room_details.py` 구현**

```python
# jforest/parsers/room_details.py
import re

from selectolax.parser import HTMLParser

_SEASON = {"비수기": "off", "성수기": "peak"}


def _int_price(s: str):
    m = re.search(r"([\d,]+)\s*원", s)
    return int(m.group(1).replace(",", "")) if m else None


def parse_room_detail(text: str) -> dict:
    tree = HTMLParser(text)
    page_text = tree.body.text(separator="\n", strip=True) if tree.body else ""

    capacity_standard = capacity_max = area = amenities = None
    for tr in tree.css("tr"):
        th = tr.css_first("th")
        td = tr.css_first("td")
        if not th or not td:
            continue
        label = th.text(strip=True)
        val = td.text(separator=" ", strip=True)
        if "인실" in label or "면적" in label:
            m1 = re.search(r"기준인원\s*[:：]?\s*(\d+)", val)
            m2 = re.search(r"최대인원\s*[:：]?\s*(\d+)", val)
            m3 = re.search(r"면적\s*[:：]?\s*([\d.]+\s*㎡)", val)
            capacity_standard = int(m1.group(1)) if m1 else capacity_standard
            capacity_max = int(m2.group(1)) if m2 else capacity_max
            area = m3.group(1) if m3 else area
        elif "편의시설" in label:
            amenities = val

    # 가격표: th(비수기/성수기, rowspan) 다음 td들이 평일/주말 요금
    prices = []
    current_season = None
    for tr in tree.css("tr"):
        th = tr.css_first("th")
        if th and th.text(strip=True) in _SEASON:
            current_season = _SEASON[th.text(strip=True)]
        for td in tr.css("td"):
            cell = td.text(strip=True)
            if "요금" not in cell or current_season is None:
                continue
            day_type = "weekday" if "평일" in cell else ("weekend" if "주말" in cell else None)
            price = _int_price(cell)
            if day_type and price is not None:
                prices.append({
                    "season": current_season, "day_type": day_type,
                    "raw_label": cell, "price": price,
                })

    # 이용안내 본문
    usage_guide = None
    for p in tree.css("p.wd_txt"):
        t = p.text(separator="\n", strip=True)
        if t:
            usage_guide = t
            break
    if not usage_guide:
        usage_guide = page_text

    ci = re.search(r"입실\s*[:：]?\s*([^\n※]+)", usage_guide or "")
    co = re.search(r"퇴실\s*[:：]?\s*([^\n※]+)", usage_guide or "")
    return {
        "capacity_standard": capacity_standard,
        "capacity_max": capacity_max,
        "area": area,
        "amenities": amenities,
        "usage_guide": usage_guide,
        "checkin_time": ci.group(1).strip() if ci else None,
        "checkout_time": co.group(1).strip() if co else None,
        "prices": prices,
    }
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_parser_room_details.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add jforest/parsers/room_details.py tests/test_parser_room_details.py
git commit -m "feat: room detail parser (capacity/area/prices/texts)"
```

---

## Task 9: 객실 상세 crawler (`crawlers/room_details.py`)

**Files:**
- Create: `jforest/crawlers/room_details.py`
- Test: `tests/test_crawler_room_details.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_crawler_room_details.py
import sqlite3, httpx
from pathlib import Path
from jforest.db import init_db
from jforest.http import Client
from jforest.crawlers.room_details import run
from jforest.util import now_iso

FX = Path(__file__).parent / "fixtures"

def test_run_fills_prices_and_usage():
    body = (FX / "room_detail.html").read_text(encoding="utf-8")
    def handler(request):
        return httpx.Response(200, text=body)
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    conn.execute("INSERT INTO forests (instt_id, name, fetched_at) VALUES ('ID02030124','x',?)", (now_iso(),))
    conn.execute("INSERT INTO rooms (goods_id, instt_id, fetched_at) VALUES "
                 "('GID020301240100101001001000004','ID02030124',?)", (now_iso(),)); conn.commit()
    client = Client(conn, delay=0, transport=httpx.MockTransport(handler))
    s = run(conn, client)
    np = conn.execute("SELECT COUNT(*) FROM room_prices").fetchone()[0]
    assert np == 4
    cap = conn.execute("SELECT capacity_standard, capacity_max FROM rooms").fetchone()
    assert cap["capacity_standard"] == 2 and cap["capacity_max"] == 3
    ug = conn.execute("SELECT usage_guide FROM room_usage_texts").fetchone()["usage_guide"]
    assert ug and len(ug) > 10
    assert s.ok == 1

def test_rerun_replaces_prices_not_duplicates():
    body = (FX / "room_detail.html").read_text(encoding="utf-8")
    def handler(request):
        return httpx.Response(200, text=body)
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    conn.execute("INSERT INTO rooms (goods_id, instt_id, fetched_at) VALUES "
                 "('GID020301240100101001001000004','ID02030124',?)", (now_iso(),)); conn.commit()
    client = Client(conn, delay=0, transport=httpx.MockTransport(handler))
    run(conn, client, force=True)
    run(conn, client, force=True)
    assert conn.execute("SELECT COUNT(*) FROM room_prices").fetchone()[0] == 4
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_crawler_room_details.py -v`
Expected: FAIL

- [ ] **Step 3: `crawlers/room_details.py` 구현**

```python
# jforest/crawlers/room_details.py
from jforest.http import BASE
from jforest.db import save_raw
from jforest.parsers.room_details import parse_room_detail
from jforest.util import now_iso, Summary

DTL_URL = f"{BASE}/pot/rm/fa/selectFcltsArmpDtlView.do"


def run(conn, client, *, limit=None, force=False) -> Summary:
    s = Summary()
    rooms = list(conn.execute("SELECT goods_id, instt_id FROM rooms ORDER BY goods_id"))
    if limit:
        rooms = rooms[:limit]
    for room in rooms:
        gid, iid = room["goods_id"], room["instt_id"]
        if not force:
            done = conn.execute("SELECT 1 FROM room_usage_texts WHERE goods_id=?", (gid,)).fetchone()
            if done:
                s.skipped += 1
                continue
        status, body = client.get(DTL_URL, params={"insttId": iid, "goodsId": gid})
        save_raw(conn, DTL_URL, "room_detail", gid, status, body, now_iso())
        if status != 200:
            s.failed += 1; s.failures.append(f"{gid} HTTP {status}"); continue
        try:
            d = parse_room_detail(body)
        except Exception as e:
            s.failed += 1; s.failures.append(f"{gid} parse: {e}"); continue
        ts = now_iso()
        conn.execute(
            "UPDATE rooms SET capacity_standard=?, capacity_max=COALESCE(?, capacity_max), "
            "area=COALESCE(?, area) WHERE goods_id=?",
            (d["capacity_standard"], d["capacity_max"], d["area"], gid),
        )
        conn.execute("DELETE FROM room_prices WHERE goods_id=?", (gid,))
        for p in d["prices"]:
            conn.execute(
                "INSERT INTO room_prices (goods_id, season, day_type, raw_label, price, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (gid, p["season"], p["day_type"], p["raw_label"], p["price"], ts),
            )
        conn.execute(
            "INSERT OR REPLACE INTO room_usage_texts "
            "(goods_id, checkin_time, checkout_time, amenities, usage_guide, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (gid, d["checkin_time"], d["checkout_time"], d["amenities"], d["usage_guide"], ts),
        )
        conn.commit()
        s.ok += 1
    return s
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_crawler_room_details.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add jforest/crawlers/room_details.py tests/test_crawler_room_details.py
git commit -m "feat: room detail crawler"
```

---

## Task 10: 할인정책 parser + crawler

**Files:**
- Create: `jforest/parsers/discounts.py`
- Create: `jforest/crawlers/discounts.py`
- Test: `tests/test_parser_discounts.py`
- Test: `tests/test_crawler_discounts.py`

실제 구조(검증): thead 3중 행. 데이터 `<tr><th>대상</th><td>구분</td><td>시점</td><td>적용일시</td>` + 객실 4 td(비수기 주중/주말, 성수기 주중/주말) + 야영장 4 td + 부대시설 4 td.

- [ ] **Step 1: parser 실패 테스트 작성**

```python
# tests/test_parser_discounts.py
from pathlib import Path
from jforest.parsers.discounts import parse_discounts
import json

FX = Path(__file__).parent / "fixtures"

def test_parse_discounts_first_row():
    rows = parse_discounts((FX / "discount.html").read_text(encoding="utf-8"))
    assert len(rows) >= 1
    r = rows[0]
    assert "장애인" in r["target"]
    assert r["category"] == "정율"
    assert r["timing"] == "결제시할인"
    assert r["apply_date"] == "2000-01-01"
    room = json.loads(r["room_rates"])
    assert room["off_weekday"] == "50%"
```

- [ ] **Step 2: parser 테스트 실패 확인**

Run: `uv run pytest tests/test_parser_discounts.py -v`
Expected: FAIL

- [ ] **Step 3: `parsers/discounts.py` 구현**

```python
# jforest/parsers/discounts.py
import json

from selectolax.parser import HTMLParser


def _rates(cells: list[str]) -> str:
    keys = ["off_weekday", "off_weekend", "peak_weekday", "peak_weekend"]
    return json.dumps(dict(zip(keys, cells)), ensure_ascii=False)


def parse_discounts(text: str) -> list[dict]:
    tree = HTMLParser(text)
    rows = []
    for tr in tree.css("tbody tr"):
        th = tr.css_first("th")
        tds = [td.text(separator=" ", strip=True).replace("\xa0", " ") for td in tr.css("td")]
        if not th or len(tds) < 15:
            continue
        target = th.text(strip=True).replace("\xa0", " ")
        rows.append({
            "target": target,
            "category": tds[0],
            "timing": tds[1],
            "apply_date": tds[2],
            "room_rates": _rates(tds[3:7]),
            "campsite_rate": _rates(tds[7:11]),
            "facility_rate": _rates(tds[11:15]),
        })
    return rows
```

- [ ] **Step 4: parser 테스트 통과 확인**

Run: `uv run pytest tests/test_parser_discounts.py -v`
Expected: PASS

- [ ] **Step 5: crawler 실패 테스트 작성**

```python
# tests/test_crawler_discounts.py
import sqlite3, httpx
from pathlib import Path
from jforest.db import init_db
from jforest.http import Client
from jforest.crawlers.discounts import run
from jforest.util import now_iso

FX = Path(__file__).parent / "fixtures"

def test_run_inserts_discount_rows():
    body = (FX / "discount.html").read_text(encoding="utf-8")
    def handler(request):
        return httpx.Response(200, text=body)
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    conn.execute("INSERT INTO forests (instt_id, name, fetched_at) VALUES ('0113','가리왕산',?)", (now_iso(),)); conn.commit()
    client = Client(conn, delay=0, transport=httpx.MockTransport(handler))
    s = run(conn, client)
    n = conn.execute("SELECT COUNT(*) FROM discount_policies WHERE instt_id='0113'").fetchone()[0]
    assert n >= 1 and s.ok == 1

def test_rerun_replaces_not_duplicates():
    body = (FX / "discount.html").read_text(encoding="utf-8")
    def handler(request):
        return httpx.Response(200, text=body)
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    conn.execute("INSERT INTO forests (instt_id, name, fetched_at) VALUES ('0113','x',?)", (now_iso(),)); conn.commit()
    client = Client(conn, delay=0, transport=httpx.MockTransport(handler))
    run(conn, client, force=True)
    n1 = conn.execute("SELECT COUNT(*) FROM discount_policies").fetchone()[0]
    run(conn, client, force=True)
    n2 = conn.execute("SELECT COUNT(*) FROM discount_policies").fetchone()[0]
    assert n1 == n2
```

- [ ] **Step 6: crawler 테스트 실패 확인**

Run: `uv run pytest tests/test_crawler_discounts.py -v`
Expected: FAIL

- [ ] **Step 7: `crawlers/discounts.py` 구현**

```python
# jforest/crawlers/discounts.py
from jforest.http import BASE
from jforest.db import save_raw
from jforest.parsers.discounts import parse_discounts
from jforest.util import now_iso, Summary

URL = f"{BASE}/pot/rm/ug/selectDcPolicyView.do"


def run(conn, client, *, limit=None, force=False) -> Summary:
    s = Summary()
    forests = list(conn.execute("SELECT instt_id FROM forests ORDER BY instt_id"))
    if limit:
        forests = forests[:limit]
    for f in forests:
        iid = f["instt_id"]
        if not force:
            done = conn.execute("SELECT 1 FROM raw_pages WHERE page_type='discount' AND ref_key=?", (iid,)).fetchone()
            if done:
                s.skipped += 1; continue
        status, body = client.get(URL, params={"hmpgId": "FRIP", "menuId": "002004", "insttId": iid})
        save_raw(conn, URL, "discount", iid, status, body, now_iso())
        if status != 200:
            s.failed += 1; s.failures.append(f"{iid} HTTP {status}"); continue
        try:
            rows = parse_discounts(body)
        except Exception as e:
            s.failed += 1; s.failures.append(f"{iid} parse: {e}"); continue
        conn.execute("DELETE FROM discount_policies WHERE instt_id=?", (iid,))
        ts = now_iso()
        for r in rows:
            conn.execute(
                "INSERT INTO discount_policies "
                "(instt_id, target, category, timing, apply_date, room_rates, campsite_rate, facility_rate, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (iid, r["target"], r["category"], r["timing"], r["apply_date"],
                 r["room_rates"], r["campsite_rate"], r["facility_rate"], ts),
            )
        conn.commit()
        s.ok += 1
    return s
```

- [ ] **Step 8: crawler 테스트 통과 확인**

Run: `uv run pytest tests/test_crawler_discounts.py -v`
Expected: PASS (2 passed)

- [ ] **Step 9: Commit**

```bash
git add jforest/parsers/discounts.py jforest/crawlers/discounts.py tests/test_parser_discounts.py tests/test_crawler_discounts.py
git commit -m "feat: discount policy parser + crawler"
```

---

## Task 11: 예약정책 parser + crawler

**Files:**
- Create: `jforest/parsers/policies.py`
- Create: `jforest/crawlers/policies.py`
- Test: `tests/test_parser_policies.py`
- Test: `tests/test_crawler_policies.py`

**전체 표(`policy_all`) 실제 구조 (라이브 검증):** `tbody`가 2개이며 **두 번째 tbody가 데이터**(첫 번째는 sticky 헤더 복제본, 빈 셀). 데이터 행 셀 순서:

```
[구분(국립), 지역(서울인천경기), 시군(가평군), 휴양림명(유명산 자연휴양림),
 객실(O), 야영장(O), 대기(O), 선착순-6주수요일(O…09시 오픈), 선착순-익월말(''),
 추첨제(주말, 성수기, …), 우선예약(바우처)]
```

선행 컬럼(구분/지역/시군)은 **rowspan**으로 다음 행에서 생략될 수 있으므로 **고정 인덱스를 쓰지 않고 '휴양림'이 든 셀을 앵커**로 잡아 그 뒤 컬럼을 상대 오프셋으로 읽는다. 후행 컬럼(운영/예약방법/우선)은 rowspan을 쓰지 않아 앵커 기준 오프셋이 안정적이다.

**개별 정책(`policy_detail`):** `selectRsrvtGdncView.do?...&menuId={004001001|002|003}&ruleId={101|102|103}` (101 선착순 / 102 주말추첨 / 103 성수기추첨). 전체 표에서 운영 종류를 확인한 뒤 해당 정책 페이지 본문 텍스트를 `fcfs_detail`/`lottery_detail`에 채운다.

- [ ] **Step 1: parser 실패 테스트 작성**

```python
# tests/test_parser_policies.py
from pathlib import Path
from jforest.parsers.policies import parse_policy_all, parse_policy_detail

FX = Path(__file__).parent / "fixtures"

def test_parse_policy_all_returns_rows_anchored_on_name():
    rows = parse_policy_all((FX / "policy_all.html").read_text(encoding="utf-8"))
    assert len(rows) >= 50
    sample = rows[0]
    assert set(sample) >= {"name", "operates_rooms", "operates_campsite",
                           "operates_waitlist", "fcfs_method", "lottery_types", "priority_types"}
    assert "휴양림" in (sample["name"] or "")
    assert sample["operates_rooms"] in (0, 1)
    # 최소 한 곳은 객실 운영(1)
    assert any(r["operates_rooms"] == 1 for r in rows)

def test_parse_policy_all_has_known_forest_name():
    rows = parse_policy_all((FX / "policy_all.html").read_text(encoding="utf-8"))
    names = " ".join(r["name"] for r in rows if r["name"])
    assert "가리왕산" in names or "유명산" in names

def test_parse_policy_detail_returns_text():
    txt = parse_policy_detail((FX / "policy_detail.html").read_text(encoding="utf-8"))
    assert txt and len(txt) > 20
    assert "선착순" in txt or "예약" in txt
```

- [ ] **Step 2: parser 테스트 실패 확인**

Run: `uv run pytest tests/test_parser_policies.py -v`
Expected: FAIL

- [ ] **Step 3: `parsers/policies.py` 구현**

```python
# jforest/parsers/policies.py
import json
import re

from selectolax.parser import HTMLParser


def _flag(text: str) -> int:
    t = (text or "").strip()
    return 1 if any(k in t for k in ("O", "o", "○", "●", "ㅇ", "운영", "가능")) else 0


def _has(text: str) -> bool:
    return bool((text or "").strip())


def _tokens(text: str):
    parts = [p.strip() for p in re.split(r"[,/·]", text or "") if p.strip()]
    return parts


def parse_policy_all(text: str) -> list[dict]:
    tree = HTMLParser(text)
    rows = []
    for tr in tree.css("tbody tr"):
        cells = [c.text(separator=" ", strip=True).replace("\xa0", " ") for c in tr.css("th, td")]
        # 휴양림명 셀을 앵커로 찾는다 (헤더 라벨 '휴양림' 단독은 제외)
        j = next((i for i, c in enumerate(cells)
                  if "휴양림" in c and c.strip() != "휴양림"), None)
        if j is None or len(cells) < j + 8:
            continue
        lottery = _tokens(cells[j + 6])
        priority = _tokens(cells[j + 7])
        if _has(cells[j + 4]):
            fcfs = "6주 수요일"
        elif _has(cells[j + 5]):
            fcfs = "익월말"
        else:
            fcfs = None
        rows.append({
            "name": cells[j],
            "operates_rooms": _flag(cells[j + 1]),
            "operates_campsite": _flag(cells[j + 2]),
            "operates_waitlist": _flag(cells[j + 3]),
            "fcfs_method": fcfs,
            "lottery_types": json.dumps(lottery, ensure_ascii=False) if lottery else None,
            "priority_types": json.dumps(priority, ensure_ascii=False) if priority else None,
        })
    return rows


def parse_policy_detail(text: str) -> str:
    tree = HTMLParser(text)
    for tag in tree.css("script, style"):
        tag.decompose()
    body = tree.body
    raw = body.text(separator="\n", strip=True) if body else ""
    cleaned = re.sub(r"\n{2,}", "\n", raw)
    return cleaned[:8000]
```

> 주: 앵커 방식이라 rowspan으로 선행 셀이 빠진 행도 정확히 읽는다. `test_parse_policy_all_returns_rows_anchored_on_name`이 깨지면 아래 디버그로 데이터 tbody의 실제 셀 배열을 확인한다.

Debug(필요 시): `uv run python -c "from selectolax.parser import HTMLParser; t=HTMLParser(open('tests/fixtures/policy_all.html',encoding='utf-8').read()); rows=[[c.text(strip=True) for c in tr.css('th,td')] for tr in t.css('tbody tr')]; print(next(r for r in rows if any('휴양림' in c and c!='휴양림' for c in r)))"`

- [ ] **Step 4: parser 테스트 통과 확인**

Run: `uv run pytest tests/test_parser_policies.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: crawler 실패 테스트 작성**

```python
# tests/test_crawler_policies.py
import sqlite3, httpx
from pathlib import Path
from jforest.db import init_db
from jforest.http import Client
from jforest.crawlers.policies import run
from jforest.util import now_iso

FX = Path(__file__).parent / "fixtures"

def test_run_matches_and_fills_detail():
    all_body = (FX / "policy_all.html").read_text(encoding="utf-8")
    detail_body = (FX / "policy_detail.html").read_text(encoding="utf-8")
    def handler(request):
        if "selectFripRsrvtPolcyView" in request.url.path:
            return httpx.Response(200, text=all_body)
        if "selectRsrvtGdncView" in request.url.path:
            return httpx.Response(200, text=detail_body)
        return httpx.Response(404)
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    # 전체 표에 등장하는 휴양림명(부분 매칭) — fixture의 실제 표기를 디버그로 확인해 맞춘다
    conn.execute("INSERT INTO forests (instt_id, name, fetched_at) VALUES ('0113','가리왕산',?)", (now_iso(),)); conn.commit()
    client = Client(conn, delay=0, transport=httpx.MockTransport(handler))
    run(conn, client)
    assert conn.execute("SELECT COUNT(*) FROM raw_pages WHERE page_type='policy_all'").fetchone()[0] == 1
    row = conn.execute("SELECT fcfs_detail FROM reservation_policies WHERE instt_id='0113'").fetchone()
    assert row is not None and row["fcfs_detail"] and len(row["fcfs_detail"]) > 20
    # 개별 정책 raw도 복합 ref_key로 저장
    pd = conn.execute("SELECT COUNT(*) FROM raw_pages WHERE page_type='policy_detail' AND ref_key LIKE '0113:%'").fetchone()[0]
    assert pd >= 1
```

> 주: 위 테스트의 심는 이름('가리왕산')은 fixture 전체 표의 실제 표기를 디버그로 확인해 맞춘다(부분 문자열 매칭).

- [ ] **Step 6: crawler 테스트 실패 확인**

Run: `uv run pytest tests/test_crawler_policies.py -v`
Expected: FAIL

- [ ] **Step 7: `crawlers/policies.py` 구현**

```python
# jforest/crawlers/policies.py
import json

from jforest.http import BASE
from jforest.db import save_raw
from jforest.parsers.policies import parse_policy_all, parse_policy_detail
from jforest.util import now_iso, Summary

ALL_URL = f"{BASE}/pot/cc/bb/selectFripRsrvtPolcyView.do"
GDNC_URL = f"{BASE}/pot/rm/ug/selectRsrvtGdncView.do"
# ruleId → (menuId, 용도)
RULE_FCFS = ("101", "004001001")
RULE_WEEKEND = ("102", "004001002")
RULE_PEAK = ("103", "004001003")


def _match_instt(forests, name):
    if not name:
        return None
    for f in forests:
        fn = f["name"] or ""
        if fn and (fn in name or name in fn):
            return f["instt_id"]
        core = fn.replace("국립", "").replace("자연휴양림", "").replace(" ", "")
        if core and core in name.replace(" ", ""):
            return f["instt_id"]
    return None


def _fetch_detail(conn, client, iid, rule, menu):
    status, body = client.get(GDNC_URL, params={"hmpgId": iid, "menuId": menu, "ruleId": rule})
    save_raw(conn, GDNC_URL, "policy_detail", f"{iid}:{rule}", status, body, now_iso())
    if status != 200:
        return None
    try:
        return parse_policy_detail(body)
    except Exception:
        return None


def run(conn, client, *, limit=None, force=False) -> Summary:
    s = Summary()
    status, body = client.get(ALL_URL, params={"hmpgId": "FRIP", "menuId": "002002"})
    save_raw(conn, ALL_URL, "policy_all", "ALL", status, body, now_iso())
    if status != 200:
        s.failed += 1; s.failures.append(f"policy_all HTTP {status}"); return s
    try:
        rows = parse_policy_all(body)
    except Exception as e:
        s.failed += 1; s.failures.append(f"policy_all parse: {e}"); return s
    forests = list(conn.execute("SELECT instt_id, name FROM forests"))
    ts = now_iso()
    matched = []
    for r in rows:
        iid = _match_instt(forests, r["name"])
        if not iid:
            s.skipped += 1; continue
        conn.execute(
            "INSERT OR REPLACE INTO reservation_policies "
            "(instt_id, operates_rooms, operates_campsite, operates_waitlist, "
            "fcfs_method, lottery_types, priority_types, fcfs_detail, lottery_detail, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)",
            (iid, r["operates_rooms"], r["operates_campsite"], r["operates_waitlist"],
             r["fcfs_method"], r["lottery_types"], r["priority_types"], ts),
        )
        matched.append((iid, r))
        s.ok += 1
    conn.commit()

    # 개별 정책 페이지로 fcfs_detail / lottery_detail 보강
    if limit:
        matched = matched[:limit]
    for iid, r in matched:
        if r["fcfs_method"]:
            fd = _fetch_detail(conn, client, iid, *RULE_FCFS)
            if fd:
                conn.execute("UPDATE reservation_policies SET fcfs_detail=? WHERE instt_id=?", (fd, iid))
        lottery = json.loads(r["lottery_types"]) if r["lottery_types"] else []
        joined = " ".join(lottery)
        if "주말" in joined:
            ld = _fetch_detail(conn, client, iid, *RULE_WEEKEND)
        elif "성수기" in joined:
            ld = _fetch_detail(conn, client, iid, *RULE_PEAK)
        else:
            ld = None
        if ld:
            conn.execute("UPDATE reservation_policies SET lottery_detail=? WHERE instt_id=?", (ld, iid))
        conn.commit()
    return s
```

> 주: 테스트의 mock 핸들러는 `selectRsrvtGdncView`에 항상 detail_body를 반환하므로, 가리왕산은 선착순(101)을 운영해 `fcfs_detail`이 채워진다(전체 표에서 `fcfs_method`가 잡힌 경우). 전체 표에서 fcfs가 비어 있으면 `fcfs_detail` 단언이 실패할 수 있으니, 디버그로 가리왕산 행의 fcfs 셀을 확인해 테스트 대상 휴양림을 선착순 운영 휴양림으로 맞춘다.

- [ ] **Step 8: crawler 테스트 통과 확인**

Run: `uv run pytest tests/test_crawler_policies.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add jforest/parsers/policies.py jforest/crawlers/policies.py tests/test_parser_policies.py tests/test_crawler_policies.py
git commit -m "feat: reservation policy parser (anchored) + crawler (all-table + policy_detail)"
```

---

## Task 12: 공지 parser (`parsers/notices.py`)

**Files:**
- Create: `jforest/parsers/notices.py`
- Test: `tests/test_parser_notices.py`

실제 구조(검증): 목록 행 `<a onClick="fn_goDtlView('250396');" class="title">제목</a>` + 같은 tr의 날짜 td(`YYYY-MM-DD`); `var totPage = 5`. 상세: 제목 `div.board_view .view_bg strong`; 첨부는 `<li><span>2026년 봄철 산불조심기간 공고문.pdf</span><a … onClick="fn_goFileDown('FILEMSTER_00172858', '184669')">` 형태 → **파일명은 `fn_goFileDown` 앵커와 같은 `<li>`의 `<span>`** 에서 추출.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_parser_notices.py
from pathlib import Path
from jforest.parsers.notices import parse_notice_list, find_tot_page, parse_notice_detail

FX = Path(__file__).parent / "fixtures"

def test_find_tot_page():
    body = (FX / "notice_list.html").read_text(encoding="utf-8")
    assert find_tot_page(body) >= 1

def test_parse_notice_list_extracts_twbbs_ids():
    body = (FX / "notice_list.html").read_text(encoding="utf-8")
    items = parse_notice_list(body)
    assert len(items) >= 1
    ids = {it["twbbs_id"] for it in items}
    assert "250396" in ids
    it = next(it for it in items if it["twbbs_id"] == "250396")
    assert it["title"] and "산불" in it["title"]

def test_parse_notice_detail_title_and_attachment():
    body = (FX / "notice_detail.html").read_text(encoding="utf-8")
    d = parse_notice_detail(body)
    assert "산불" in (d["title"] or "")
    assert d["body_text"] and len(d["body_text"]) > 5
    files = {(a["file_master_id"], a["file_id"]) for a in d["attachments"]}
    assert ("FILEMSTER_00172858", "184669") in files
    # 파일명도 같은 li의 span에서 추출
    att = next(a for a in d["attachments"] if a["file_id"] == "184669")
    assert att["file_name"] and att["file_name"].endswith(".pdf")
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_parser_notices.py -v`
Expected: FAIL

- [ ] **Step 3: `parsers/notices.py` 구현**

```python
# jforest/parsers/notices.py
import re

from selectolax.parser import HTMLParser

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DTL = re.compile(r"fn_goDtlView\('(\d+)'\)")
_FILE = re.compile(r"fn_goFileDown\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)")


def find_tot_page(text: str) -> int:
    m = re.search(r"var\s+totPage\s*=\s*(\d+)", text)
    return int(m.group(1)) if m else 1


def parse_notice_list(text: str) -> list[dict]:
    tree = HTMLParser(text)
    items = []
    for a in tree.css("a.title"):
        onclick = a.attributes.get("onclick") or a.attributes.get("onClick") or ""
        m = _DTL.search(onclick)
        if not m:
            continue
        twbbs_id = m.group(1)
        title = a.text(strip=True)
        # 같은 행(tr)의 날짜 셀
        tr = a.parent
        while tr is not None and tr.tag != "tr":
            tr = tr.parent
        updated_at = None
        if tr is not None:
            dm = _DATE.search(tr.text(separator=" ", strip=True))
            updated_at = dm.group(0) if dm else None
        items.append({"twbbs_id": twbbs_id, "title": title, "updated_at": updated_at})
    return items


def parse_notice_detail(text: str) -> dict:
    tree = HTMLParser(text)
    title_node = tree.css_first(".board_view .view_bg strong") or tree.css_first(".view_bg strong")
    title = title_node.text(strip=True) if title_node else None
    body_node = tree.css_first(".board_view") or tree.body
    body_text = body_node.text(separator="\n", strip=True) if body_node else ""
    dm = _DATE.search(body_text)
    updated_at = dm.group(0) if dm else None
    # 첨부: fn_goFileDown 앵커마다 같은 <li>의 <span>에서 파일명 추출
    attachments = []
    seen = set()
    for a in tree.css("a"):
        oc = a.attributes.get("onclick") or a.attributes.get("onClick") or ""
        m = _FILE.search(oc)
        if not m:
            continue
        fm, fid = m.group(1), m.group(2)
        if not fm.startswith("FILEMSTER") or (fm, fid) in seen:
            continue
        seen.add((fm, fid))
        fname = None
        li = a.parent
        while li is not None and li.tag != "li":
            li = li.parent
        if li is not None:
            sp = li.css_first("span")
            if sp:
                fname = sp.text(strip=True) or None
        attachments.append({"file_master_id": fm, "file_id": fid, "file_name": fname})
    return {"title": title, "updated_at": updated_at, "body_text": body_text, "attachments": attachments}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_parser_notices.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add jforest/parsers/notices.py tests/test_parser_notices.py
git commit -m "feat: notice list/detail parser (totPage, twbbsId, fn_goFileDown)"
```

---

## Task 13: 공지 crawler + 첨부 다운로드 (`crawlers/notices.py`)

**Files:**
- Create: `jforest/crawlers/notices.py`
- Test: `tests/test_crawler_notices.py`

공지 목록은 `nowPage=1..totPage` GET 순회. 상세에서 본문/첨부 메타 저장. 첨부 다운로드는 매직바이트로 종류 보정 후 `data/attachments/`에 저장.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_crawler_notices.py
import sqlite3, httpx
from pathlib import Path
from jforest.db import init_db
from jforest.http import Client
from jforest.crawlers.notices import run, download_attachments, sniff_content_type
from jforest.util import now_iso

FX = Path(__file__).parent / "fixtures"

def test_sniff_content_type_by_magic_bytes():
    assert sniff_content_type(b"\xff\xd8\xff\xe0rest", "x") == "image/jpeg"
    assert sniff_content_type(b"%PDF-1.7", "x") == "application/pdf"
    assert sniff_content_type(b"\x89PNG\r\n", "x") == "image/png"

def test_run_collects_notices_and_attachment_meta():
    list_body = (FX / "notice_list.html").read_text(encoding="utf-8")
    detail_body = (FX / "notice_detail.html").read_text(encoding="utf-8")
    def handler(request):
        if "selectNticBbrssListView" in request.url.path:
            return httpx.Response(200, text=list_body)
        if "selectNticBbrssDtlView" in request.url.path:
            return httpx.Response(200, text=detail_body)
        return httpx.Response(404)
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    conn.execute("INSERT INTO forests (instt_id, name, fetched_at) VALUES ('0113','가리왕산',?)", (now_iso(),)); conn.commit()
    client = Client(conn, delay=0, transport=httpx.MockTransport(handler))
    run(conn, client)
    nn = conn.execute("SELECT COUNT(*) FROM notices WHERE instt_id='0113'").fetchone()[0]
    assert nn >= 1
    na = conn.execute("SELECT COUNT(*) FROM notice_attachments").fetchone()[0]
    assert na >= 1  # 250396 상세에 첨부 1건
    fn = conn.execute("SELECT file_name FROM notice_attachments WHERE file_id='184669'").fetchone()
    assert fn and fn["file_name"] and fn["file_name"].endswith(".pdf")  # span에서 파일명 추출

def test_download_attachments_writes_file(tmp_path):
    def handler(request):
        return httpx.Response(200, content=b"%PDF-1.7 data",
                              headers={"Content-Type": "application/octet-stream",
                                       "Content-Disposition": "attachment; filename=a.pdf"})
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    conn.execute("INSERT INTO notice_attachments (instt_id, twbbs_id, file_master_id, file_id, file_name, downloaded, fetched_at) "
                 "VALUES ('0113','250396','FILEMSTER_1','184669','a.pdf',0,?)", (now_iso(),)); conn.commit()
    client = Client(conn, delay=0, transport=httpx.MockTransport(handler))
    download_attachments(conn, client, dest_dir=str(tmp_path))
    row = conn.execute("SELECT downloaded, local_path, content_type FROM notice_attachments").fetchone()
    assert row["downloaded"] == 1
    assert row["content_type"] == "application/pdf"
    assert Path(row["local_path"]).exists()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_crawler_notices.py -v`
Expected: FAIL

- [ ] **Step 3: `crawlers/notices.py` 구현**

```python
# jforest/crawlers/notices.py
import os

from jforest.http import BASE
from jforest.db import save_raw
from jforest.parsers.notices import parse_notice_list, find_tot_page, parse_notice_detail
from jforest.util import now_iso, Summary

LIST_URL = f"{BASE}/pot/cc/nm/selectNticBbrssListView.do"
DTL_URL = f"{BASE}/pot/cc/nm/selectNticBbrssDtlView.do"
FILE_URL = f"{BASE}/com/cm/fileDownload.do"
BBRSS = "BBRSSMSTER_00000051"

_MAGIC = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"%PDF", "application/pdf"),
    (b"\x89PNG\r\n", "image/png"),
    (b"GIF8", "image/gif"),
    (b"PK\x03\x04", "application/zip"),  # hwpx/docx/xlsx 포함
]


def sniff_content_type(content: bytes, fallback: str) -> str:
    for sig, ct in _MAGIC:
        if content.startswith(sig):
            return ct
    return fallback


def run(conn, client, *, limit=None, force=False) -> Summary:
    s = Summary()
    forests = list(conn.execute("SELECT instt_id FROM forests ORDER BY instt_id"))
    if limit:
        forests = forests[:limit]
    for f in forests:
        iid = f["instt_id"]
        status, body = client.get(LIST_URL, params={
            "hmpgId": iid, "menuId": "005001", "bbrssMsterId": BBRSS, "nowPage": 1})
        save_raw(conn, LIST_URL, "notice_list", f"{iid}:1", status, body, now_iso())
        if status != 200:
            s.failed += 1; s.failures.append(f"{iid} list HTTP {status}"); continue
        tot = find_tot_page(body)
        all_items = parse_notice_list(body)
        for page in range(2, tot + 1):
            st, bd = client.get(LIST_URL, params={
                "hmpgId": iid, "menuId": "005001", "bbrssMsterId": BBRSS, "nowPage": page})
            save_raw(conn, LIST_URL, "notice_list", f"{iid}:{page}", st, bd, now_iso())
            if st == 200:
                all_items.extend(parse_notice_list(bd))
        for it in all_items:
            twbbs = it["twbbs_id"]
            if not force:
                done = conn.execute(
                    "SELECT 1 FROM notices WHERE instt_id=? AND twbbs_id=?", (iid, twbbs)
                ).fetchone()
                if done:
                    s.skipped += 1; continue
            dstatus, dbody = client.get(DTL_URL, params={
                "hmpgId": iid, "menuId": "005001", "twbbsId": twbbs, "bbrssMsterId": BBRSS})
            save_raw(conn, DTL_URL, "notice_detail", f"{iid}:{twbbs}", dstatus, dbody, now_iso())
            if dstatus != 200:
                s.failed += 1; s.failures.append(f"{iid}/{twbbs} HTTP {dstatus}"); continue
            d = parse_notice_detail(dbody)
            ts = now_iso()
            conn.execute(
                "INSERT OR REPLACE INTO notices (instt_id, twbbs_id, title, updated_at, body_text, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (iid, twbbs, d["title"] or it["title"], d["updated_at"] or it["updated_at"], d["body_text"], ts),
            )
            for a in d["attachments"]:
                conn.execute(
                    "INSERT OR REPLACE INTO notice_attachments "
                    "(instt_id, twbbs_id, file_master_id, file_id, file_name, content_type, local_path, downloaded, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, NULL, NULL, 0, ?)",
                    (iid, twbbs, a["file_master_id"], a["file_id"], a.get("file_name"), ts),
                )
            conn.commit()
            s.ok += 1
    return s


def download_attachments(conn, client, *, dest_dir="data/attachments", limit=None):
    s = Summary()
    os.makedirs(dest_dir, exist_ok=True)
    pending = list(conn.execute("SELECT * FROM notice_attachments WHERE downloaded=0"))
    if limit:
        pending = pending[:limit]
    for a in pending:
        status, content, headers = client.download(FILE_URL, params={
            "ATTCH_FILE_ID": a["file_id"], "ATTCH_FILE_MSTER_ID": a["file_master_id"]})
        if status != 200 or not content:
            s.failed += 1; s.failures.append(f"file {a['file_id']} HTTP {status}"); continue
        ct = sniff_content_type(content, headers.get("Content-Type", "application/octet-stream"))
        fname = a["file_name"] or f"{a['file_master_id']}_{a['file_id']}"
        path = os.path.join(dest_dir, f"{a['file_master_id']}_{a['file_id']}_{os.path.basename(fname)}")
        with open(path, "wb") as fh:
            fh.write(content)
        conn.execute(
            "UPDATE notice_attachments SET downloaded=1, local_path=?, content_type=? WHERE id=?",
            (path, ct, a["id"]),
        )
        conn.commit()
        s.ok += 1
    return s
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_crawler_notices.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add jforest/crawlers/notices.py tests/test_crawler_notices.py
git commit -m "feat: notices crawler (nowPage pagination) + attachment download with magic-byte sniff"
```

---

## Task 14: reparse + status 로직 (`reparse.py`)

**Files:**
- Create: `jforest/reparse.py`
- Test: `tests/test_reparse.py`

`reparse`는 네트워크 없이 `raw_pages`의 본문을 다시 파싱해 구조화 테이블을 채운다. `status`는 단계별 건수를 요약한다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_reparse.py
import sqlite3
from pathlib import Path
from jforest.db import init_db, save_raw
from jforest.reparse import reparse, status_counts
from jforest.util import now_iso

FX = Path(__file__).parent / "fixtures"

def test_reparse_rooms_from_raw_without_network():
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    conn.execute("INSERT INTO forests (instt_id, name, fetched_at) VALUES ('ID02030124','x',?)", (now_iso(),))
    body = (FX / "room_list.html").read_text(encoding="utf-8")
    save_raw(conn, "u", "room_list", "ID02030124", 200, body, now_iso())
    n = reparse(conn, "rooms")
    assert n >= 1
    assert conn.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] >= 1

def test_status_counts_reports_table_sizes():
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    conn.execute("INSERT INTO forests (instt_id, name, fetched_at) VALUES ('A','x',?)", (now_iso(),)); conn.commit()
    counts = status_counts(conn)
    assert counts["forests"] == 1
    assert "rooms" in counts and "notices" in counts
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_reparse.py -v`
Expected: FAIL

- [ ] **Step 3: `reparse.py` 구현**

```python
# jforest/reparse.py
from jforest.db import get_raw_pages
from jforest.parsers.forests import parse_forest_list_json, parse_forest_list_html
from jforest.parsers.rooms import parse_room_list
from jforest.parsers.room_details import parse_room_detail
from jforest.parsers.discounts import parse_discounts
from jforest.parsers.policies import parse_policy_all, parse_policy_detail
from jforest.parsers.notices import parse_notice_detail
from jforest.crawlers.policies import _match_instt
from jforest.util import now_iso

_TABLES = ["forests", "rooms", "room_prices", "room_usage_texts", "discount_policies",
           "reservation_policies", "notices", "notice_attachments", "fetch_log", "raw_pages"]


def status_counts(conn) -> dict:
    out = {}
    for t in _TABLES:
        out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    return out


def reparse(conn, step: str) -> int:
    """raw_pages에서 step 단계 본문을 다시 파싱해 구조화 테이블을 채운다. 처리 건수 반환."""
    n = 0
    if step == "forests":
        for row in get_raw_pages(conn, "forest_list_json"):
            sido = int(row["ref_key"]) if row["ref_key"].isdigit() else None
            for r in parse_forest_list_json(row["body"]):
                conn.execute(
                    "INSERT OR REPLACE INTO forests "
                    "(instt_id, name, sido_code, arcd, instt_type_code, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (r["instt_id"], r["name"], sido, r["arcd"], r["instt_type_code"], now_iso()),
                )
                n += 1
        for row in get_raw_pages(conn, "forest_list_html"):
            for it in parse_forest_list_html(row["body"]):
                conn.execute(
                    "UPDATE forests SET instt_type=COALESCE(?, instt_type), "
                    "homepage_url=COALESCE(?, homepage_url), tags=COALESCE(?, tags), "
                    "summary=COALESCE(?, summary), reservation_intake=COALESCE(?, reservation_intake) "
                    "WHERE instt_id=?",
                    (it["instt_type"], it["homepage_url"], it["tags"], it["summary"],
                     it["reservation_intake"], it["instt_id"]),
                )
    elif step == "rooms":
        for row in get_raw_pages(conn, "room_list"):
            iid = row["ref_key"]
            for r in parse_room_list(row["body"]):
                conn.execute(
                    "INSERT OR REPLACE INTO rooms "
                    "(goods_id, instt_id, room_type, name, capacity_standard, capacity_max, area, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (r["goods_id"], iid, r["room_type"], r["name"],
                     r["capacity_standard"], r["capacity_max"], r["area"], now_iso()),
                )
                n += 1
    elif step == "room-details":
        for row in get_raw_pages(conn, "room_detail"):
            gid = row["ref_key"]
            d = parse_room_detail(row["body"])
            conn.execute("DELETE FROM room_prices WHERE goods_id=?", (gid,))
            for p in d["prices"]:
                conn.execute(
                    "INSERT INTO room_prices (goods_id, season, day_type, raw_label, price, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (gid, p["season"], p["day_type"], p["raw_label"], p["price"], now_iso()),
                )
            conn.execute(
                "INSERT OR REPLACE INTO room_usage_texts "
                "(goods_id, checkin_time, checkout_time, amenities, usage_guide, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (gid, d["checkin_time"], d["checkout_time"], d["amenities"], d["usage_guide"], now_iso()),
            )
            n += 1
    elif step == "discounts":
        for row in get_raw_pages(conn, "discount"):
            iid = row["ref_key"]
            conn.execute("DELETE FROM discount_policies WHERE instt_id=?", (iid,))
            for r in parse_discounts(row["body"]):
                conn.execute(
                    "INSERT INTO discount_policies "
                    "(instt_id, target, category, timing, apply_date, room_rates, campsite_rate, facility_rate, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (iid, r["target"], r["category"], r["timing"], r["apply_date"],
                     r["room_rates"], r["campsite_rate"], r["facility_rate"], now_iso()),
                )
                n += 1
    elif step == "notices":
        for row in get_raw_pages(conn, "notice_detail"):
            iid, twbbs = row["ref_key"].split(":", 1)
            d = parse_notice_detail(row["body"])
            conn.execute(
                "INSERT OR REPLACE INTO notices (instt_id, twbbs_id, title, updated_at, body_text, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (iid, twbbs, d["title"], d["updated_at"], d["body_text"], now_iso()),
            )
            for a in d["attachments"]:
                conn.execute(
                    "INSERT OR REPLACE INTO notice_attachments "
                    "(instt_id, twbbs_id, file_master_id, file_id, file_name, content_type, local_path, downloaded, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, NULL, NULL, 0, ?)",
                    (iid, twbbs, a["file_master_id"], a["file_id"], a.get("file_name"), now_iso()),
                )
            n += 1
    elif step == "policies":
        forests = list(conn.execute("SELECT instt_id, name FROM forests"))
        for row in get_raw_pages(conn, "policy_all"):
            for r in parse_policy_all(row["body"]):
                iid = _match_instt(forests, r["name"])
                if not iid:
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO reservation_policies "
                    "(instt_id, operates_rooms, operates_campsite, operates_waitlist, "
                    "fcfs_method, lottery_types, priority_types, fcfs_detail, lottery_detail, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, "
                    "(SELECT fcfs_detail FROM reservation_policies WHERE instt_id=?), "
                    "(SELECT lottery_detail FROM reservation_policies WHERE instt_id=?), ?)",
                    (iid, r["operates_rooms"], r["operates_campsite"], r["operates_waitlist"],
                     r["fcfs_method"], r["lottery_types"], r["priority_types"], iid, iid, now_iso()),
                )
                n += 1
        for row in get_raw_pages(conn, "policy_detail"):
            iid, rule = row["ref_key"].split(":", 1)
            txt = parse_policy_detail(row["body"])
            col = "fcfs_detail" if rule == "101" else "lottery_detail"
            conn.execute(f"UPDATE reservation_policies SET {col}=? WHERE instt_id=?", (txt, iid))
    else:
        raise ValueError(f"reparse 미지원 단계: {step}")
    conn.commit()
    return n
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_reparse.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add jforest/reparse.py tests/test_reparse.py
git commit -m "feat: reparse from raw_pages + status counts"
```

---

## Task 15: CLI 조립 (`cli.py`)

**Files:**
- Create: `jforest/cli.py`
- Test: `tests/test_cli.py`

`click` 그룹: `crawl <step>`, `crawl all`, `reparse <step>`, `status`. 공통 옵션 `--db`, `--limit`, `--force`, `--delay`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_cli.py
from click.testing import CliRunner
from jforest.cli import main

def test_status_on_empty_db(tmp_path):
    db = str(tmp_path / "t.db")
    r = CliRunner().invoke(main, ["--db", db, "status"])
    assert r.exit_code == 0
    assert "forests" in r.output

def test_crawl_unknown_step_errors(tmp_path):
    db = str(tmp_path / "t.db")
    r = CliRunner().invoke(main, ["--db", db, "crawl", "bogus"])
    assert r.exit_code != 0

def test_reparse_unknown_step_errors(tmp_path):
    db = str(tmp_path / "t.db")
    r = CliRunner().invoke(main, ["--db", db, "reparse", "bogus"])
    assert r.exit_code != 0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL

- [ ] **Step 3: `cli.py` 구현**

```python
# jforest/cli.py
import click

from jforest.db import get_conn, init_db
from jforest.http import Client
from jforest.reparse import reparse as do_reparse, status_counts
from jforest.crawlers import forests, rooms, room_details, discounts, policies, notices

STEPS = {
    "forests": forests.run,
    "rooms": rooms.run,
    "room-details": room_details.run,
    "discounts": discounts.run,
    "policies": policies.run,
    "notices": notices.run,
}
ORDER = ["forests", "rooms", "room-details", "discounts", "policies", "notices"]
REPARSE_STEPS = {"forests", "rooms", "room-details", "discounts", "policies", "notices"}


@click.group()
@click.option("--db", default="data/jforest.db", help="SQLite 경로")
@click.option("--limit", type=int, default=None, help="휴양림 N곳만")
@click.option("--force", is_flag=True, help="이미 수집된 항목도 다시 수집")
@click.option("--delay", type=float, default=1.0, help="요청 간 딜레이(초)")
@click.pass_context
def main(ctx, db, limit, force, delay):
    import os
    os.makedirs(os.path.dirname(db) or ".", exist_ok=True)
    conn = get_conn(db)
    init_db(conn)
    ctx.obj = {"conn": conn, "limit": limit, "force": force, "delay": delay}


@main.command()
@click.argument("step")
@click.pass_context
def crawl(ctx, step):
    o = ctx.obj
    conn = o["conn"]
    client = Client(conn, delay=o["delay"])
    steps = ORDER if step == "all" else [step]
    for st in steps:
        if st not in STEPS:
            raise click.ClickException(f"알 수 없는 단계: {st}. 가능: {', '.join(ORDER)} 또는 all")
    for st in steps:
        click.echo(f"== crawl {st} ==")
        summary = STEPS[st](conn, client, limit=o["limit"], force=o["force"])
        click.echo(summary.line())
        if st == "notices":
            click.echo("== download attachments ==")
            ds = notices.download_attachments(conn, client, limit=o["limit"])
            click.echo("첨부 " + ds.line())
        if summary.failures:
            click.echo(f"  실패 {len(summary.failures)}건 중 상위 {min(20, len(summary.failures))}건:")
            for fail in summary.failures[:20]:
                click.echo(f"  FAIL: {fail}")


@main.command()
@click.argument("step")
@click.pass_context
def reparse(ctx, step):
    if step not in REPARSE_STEPS:
        raise click.ClickException(f"reparse 미지원 단계: {step}. 가능: {', '.join(sorted(REPARSE_STEPS))}")
    n = do_reparse(ctx.obj["conn"], step)
    click.echo(f"reparse {step}: {n}건 처리")


@main.command()
@click.pass_context
def status(ctx):
    counts = status_counts(ctx.obj["conn"])
    for table, n in counts.items():
        click.echo(f"{table:24} {n}")
```

> 주: `reparse`의 `room-details`는 `do_reparse(conn, "room-details")`로 전달된다(`reparse.py`가 동일 키 사용).

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 전체 테스트 실행**

Run: `uv run pytest -v`
Expected: 모든 테스트 PASS

- [ ] **Step 6: Commit**

```bash
git add jforest/cli.py tests/test_cli.py
git commit -m "feat: click CLI (crawl/reparse/status)"
```

---

## Task 16: 실제 사이트 스모크 테스트 (수동)

**Files:** (없음 — 수동 검증)

- [ ] **Step 1: 2곳만 실제 수집**

Run: `uv run jforest --db data/smoke.db --limit 2 --delay 1 crawl all`
Expected: 각 단계가 `성공 N건` 출력, 에러 없이 종료. `crawl notices` 후 첨부 다운로드 라인 출력.

- [ ] **Step 2: 결과 확인**

Run: `uv run jforest --db data/smoke.db status`
Expected: `forests`, `rooms`, `room_prices`, `notices` 등이 0보다 큰 값

- [ ] **Step 3: reparse 동작 확인 (네트워크 없이)**

Run: `uv run jforest --db data/smoke.db reparse rooms`
Expected: `reparse rooms: N건 처리` (N ≥ 0), 에러 없음

- [ ] **Step 4: 스모크 DB 정리 후 Commit**

```bash
rm -f data/smoke.db
git add -A
git commit -m "test: manual smoke run verified (no code change)" --allow-empty
```

---

## Self-Review 체크리스트 (작성자 확인 완료)

- **스펙 커버리지**: 10개 테이블 전부 Task 1에 생성 / 6단계 crawler(Task 5,7,9,10,11,13) / 1a+1b(Task 5) / **예약정책 개별 policy_detail 수집·fcfs_detail·lottery_detail(Task 11)** / reparse·status(Task 14) / CLI 옵션 `--limit`·`--force`·`--delay`(Task 15) / 매직바이트(Task 13) / nowPage·totPage 페이지네이션(Task 13) / goodsId raw 추출(Task 6) / insttId==hmpgId assert(Task 5) / room_prices 가변 행·raw_label(Task 8) / discount apply_date(Task 10) / **공지 첨부 file_name(Task 12·13)** / **not_available fetch_log(Task 7)** 모두 대응.
- **플레이스홀더 없음**: 모든 코드 스텝에 실제 코드 포함. fixture 의존 테스트는 검증된 실제 값(goodsId, twbbsId 250396, 가격 60000/80000, homepage `garisan.foresttrip.go.kr`) 사용.
- **타입/시그니처 일관성**: 모든 crawler `run(conn, client, *, limit, force) -> Summary`; 모든 parser 순수 함수; `now_iso`/`Summary`는 `util.py` 단일 정의; `reparse` 단계 키(`forests`/`rooms`/`room-details`/`discounts`/`policies`/`notices`)가 CLI `REPARSE_STEPS`와 일치.

## 2차 검토(라이브 재검증) 반영 이력

계획 초안을 실제 사이트와 재대조해 발견한 문제를 수정했다.

| # | 문제 | 수정 |
| --- | --- | --- |
| 1 | 예약정책 개별(policy_detail) 단계 누락 → fcfs_detail/lottery_detail 영원히 NULL | Task 11에 `selectRsrvtGdncView` ruleId 101/102/103 수집 + 본문 보강 추가, `parse_policy_detail` 신설 |
| 2 | forest HTML 파서가 DOM 셀렉터 기반인데 항목이 JS `var positions` 배열 → 동작 불가 | JS 배열 정규식 파싱으로 재작성(Task 4), 테스트를 실제 값(가리산/홈페이지 URL)으로 강화 |
| 3 | `homepage_url`에 `"hmpgId=..."` 쓰레기 저장 | info_button `<a href>`의 실제 URL 추출 |
| 4 | policy_all 컬럼 인덱스 추측(off-by-one), 빈 행/이중 tbody 미처리 | '휴양림' 셀 앵커 기반 상대 오프셋 파싱으로 재작성(rowspan 안전) |
| 5 | instt_type 라벨 출처 오류(HTML에 기관구분 없음) | 1b에서 None, `instt_type_code`(1a) 보존으로 명시 |
| 6 | 재시도 백오프가 `delay=0`에서도 실제 sleep | `_backoff`가 `delay`에 비례(테스트 무지연) |
| 7 | 공지 첨부 `file_name` 미추출 | `<li>`의 `<span>`에서 파일명 추출(Task 12·13) |
| 8 | reparse가 forests/policies 미지원 | Task 14에 두 단계 추가, CLI `REPARSE_STEPS` 갱신 |
| 9 | 메뉴 없음 시 fetch_log not_available 미기록 | Task 7에 기록 추가 |
| 10 | 미사용 import/ dead code | `parse_forest_list_html` 재작성으로 제거, `forests.py`에서 `selectolax` import 제거 |
| 11 | CLI 실패 목록 truncation 미표기 | "상위 N건" 라벨 출력 |
