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
