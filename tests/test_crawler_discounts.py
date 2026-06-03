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
