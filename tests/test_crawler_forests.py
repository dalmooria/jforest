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
