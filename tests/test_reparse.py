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
