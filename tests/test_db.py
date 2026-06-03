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
