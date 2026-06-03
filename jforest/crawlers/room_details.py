# jforest/crawlers/room_details.py
from jforest.http import BASE
from jforest.db import save_raw
from jforest.parsers.room_details import parse_room_detail
from jforest.util import now_iso, Summary

DTL_URL = f"{BASE}/pot/rm/fa/selectFcltsArmpDtlView.do"


def run(conn, client, *, limit=None, force=False) -> Summary:
    s = Summary()
    rooms = list(conn.execute("SELECT goods_id, instt_id FROM rooms ORDER BY goods_id"))
    if limit:
        rooms = rooms[:limit]
    for room in rooms:
        gid, iid = room["goods_id"], room["instt_id"]
        if not force:
            done = conn.execute("SELECT 1 FROM room_usage_texts WHERE goods_id=?", (gid,)).fetchone()
            if done:
                s.skipped += 1
                continue
        status, body = client.get(DTL_URL, params={"insttId": iid, "goodsId": gid})
        save_raw(conn, DTL_URL, "room_detail", gid, status, body, now_iso())
        if status != 200:
            s.failed += 1; s.failures.append(f"{gid} HTTP {status}"); continue
        try:
            d = parse_room_detail(body)
        except Exception as e:
            s.failed += 1; s.failures.append(f"{gid} parse: {e}"); continue
        ts = now_iso()
        conn.execute(
            "UPDATE rooms SET capacity_standard=?, capacity_max=COALESCE(?, capacity_max), "
            "area=COALESCE(?, area) WHERE goods_id=?",
            (d["capacity_standard"], d["capacity_max"], d["area"], gid),
        )
        conn.execute("DELETE FROM room_prices WHERE goods_id=?", (gid,))
        for p in d["prices"]:
            conn.execute(
                "INSERT INTO room_prices (goods_id, season, day_type, raw_label, price, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (gid, p["season"], p["day_type"], p["raw_label"], p["price"], ts),
            )
        conn.execute(
            "INSERT OR REPLACE INTO room_usage_texts "
            "(goods_id, checkin_time, checkout_time, amenities, usage_guide, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (gid, d["checkin_time"], d["checkout_time"], d["amenities"], d["usage_guide"], ts),
        )
        conn.commit()
        s.ok += 1
    return s
