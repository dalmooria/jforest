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
