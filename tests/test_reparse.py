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

def test_reparse_room_details_fills_capacity_standard_like_live():
    # reparse는 라이브 크롤러와 동일한 구조화 결과를 내야 한다:
    # capacity_standard는 상세 페이지에만 있으므로 reparse room-details가 rooms를 보강해야 한다.
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    gid = "GID020301240100101001001000004"
    conn.execute("INSERT INTO rooms (goods_id, instt_id, capacity_standard, fetched_at) "
                 "VALUES (?, 'ID02030124', NULL, ?)", (gid, now_iso()))
    body = (FX / "room_detail.html").read_text(encoding="utf-8")
    save_raw(conn, "u", "room_detail", gid, 200, body, now_iso())
    conn.commit()
    reparse(conn, "room-details")
    cap = conn.execute("SELECT capacity_standard, capacity_max FROM rooms WHERE goods_id=?", (gid,)).fetchone()
    assert cap["capacity_standard"] == 2
    assert cap["capacity_max"] == 3
    assert conn.execute("SELECT COUNT(*) FROM room_prices WHERE goods_id=?", (gid,)).fetchone()[0] == 4


def test_status_counts_reports_table_sizes():
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    conn.execute("INSERT INTO forests (instt_id, name, fetched_at) VALUES ('A','x',?)", (now_iso(),)); conn.commit()
    counts = status_counts(conn)
    assert counts["forests"] == 1
    assert "rooms" in counts and "notices" in counts
