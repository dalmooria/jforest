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
