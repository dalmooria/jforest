# jforest/crawlers/discounts.py
from jforest.http import BASE
from jforest.db import save_raw
from jforest.parsers.discounts import parse_discounts
from jforest.util import now_iso, Summary

URL = f"{BASE}/pot/rm/ug/selectDcPolicyView.do"


def run(conn, client, *, limit=None, force=False) -> Summary:
    s = Summary()
    forests = list(conn.execute("SELECT instt_id FROM forests ORDER BY instt_id"))
    if limit:
        forests = forests[:limit]
    for f in forests:
        iid = f["instt_id"]
        if not force:
            done = conn.execute("SELECT 1 FROM raw_pages WHERE page_type='discount' AND ref_key=?", (iid,)).fetchone()
            if done:
                s.skipped += 1; continue
        status, body = client.get(URL, params={"hmpgId": "FRIP", "menuId": "002004", "insttId": iid})
        save_raw(conn, URL, "discount", iid, status, body, now_iso())
        if status != 200:
            s.failed += 1; s.failures.append(f"{iid} HTTP {status}"); continue
        try:
            rows = parse_discounts(body)
        except Exception as e:
            s.failed += 1; s.failures.append(f"{iid} parse: {e}"); continue
        conn.execute("DELETE FROM discount_policies WHERE instt_id=?", (iid,))
        ts = now_iso()
        for r in rows:
            conn.execute(
                "INSERT INTO discount_policies "
                "(instt_id, target, category, timing, apply_date, room_rates, campsite_rate, facility_rate, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (iid, r["target"], r["category"], r["timing"], r["apply_date"],
                 r["room_rates"], r["campsite_rate"], r["facility_rate"], ts),
            )
        conn.commit()
        s.ok += 1
    return s
