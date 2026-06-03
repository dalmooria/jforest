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
