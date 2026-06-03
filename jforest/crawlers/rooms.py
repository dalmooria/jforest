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
