# jforest/crawlers/policies.py
import json

from jforest.http import BASE
from jforest.db import save_raw
from jforest.parsers.policies import parse_policy_all, parse_policy_detail
from jforest.util import now_iso, Summary

ALL_URL = f"{BASE}/pot/cc/bb/selectFripRsrvtPolcyView.do"
GDNC_URL = f"{BASE}/pot/rm/ug/selectRsrvtGdncView.do"
# ruleId → (menuId, 용도)
RULE_FCFS = ("101", "004001001")
RULE_WEEKEND = ("102", "004001002")
RULE_PEAK = ("103", "004001003")


def _match_instt(forests, name):
    if not name:
        return None
    for f in forests:
        fn = f["name"] or ""
        if fn and (fn in name or name in fn):
            return f["instt_id"]
        core = fn.replace("국립", "").replace("자연휴양림", "").replace(" ", "")
        if core and core in name.replace(" ", ""):
            return f["instt_id"]
    return None


def _fetch_detail(conn, client, iid, rule, menu):
    status, body = client.get(GDNC_URL, params={"hmpgId": iid, "menuId": menu, "ruleId": rule})
    save_raw(conn, GDNC_URL, "policy_detail", f"{iid}:{rule}", status, body, now_iso())
    if status != 200:
        return None
    try:
        return parse_policy_detail(body)
    except Exception:
        return None


def run(conn, client, *, limit=None, force=False) -> Summary:
    s = Summary()
    status, body = client.get(ALL_URL, params={"hmpgId": "FRIP", "menuId": "002002"})
    save_raw(conn, ALL_URL, "policy_all", "ALL", status, body, now_iso())
    if status != 200:
        s.failed += 1; s.failures.append(f"policy_all HTTP {status}"); return s
    try:
        rows = parse_policy_all(body)
    except Exception as e:
        s.failed += 1; s.failures.append(f"policy_all parse: {e}"); return s
    forests = list(conn.execute("SELECT instt_id, name FROM forests"))
    ts = now_iso()
    matched = []
    for r in rows:
        iid = _match_instt(forests, r["name"])
        if not iid:
            s.skipped += 1; continue
        conn.execute(
            "INSERT OR REPLACE INTO reservation_policies "
            "(instt_id, operates_rooms, operates_campsite, operates_waitlist, "
            "fcfs_method, lottery_types, priority_types, fcfs_detail, lottery_detail, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)",
            (iid, r["operates_rooms"], r["operates_campsite"], r["operates_waitlist"],
             r["fcfs_method"], r["lottery_types"], r["priority_types"], ts),
        )
        matched.append((iid, r))
        s.ok += 1
    conn.commit()

    # 개별 정책 페이지로 fcfs_detail / lottery_detail 보강
    if limit:
        matched = matched[:limit]
    for iid, r in matched:
        if r["fcfs_method"]:
            fd = _fetch_detail(conn, client, iid, *RULE_FCFS)
            if fd:
                conn.execute("UPDATE reservation_policies SET fcfs_detail=? WHERE instt_id=?", (fd, iid))
        lottery = json.loads(r["lottery_types"]) if r["lottery_types"] else []
        joined = " ".join(lottery)
        if "주말" in joined:
            ld = _fetch_detail(conn, client, iid, *RULE_WEEKEND)
        elif "성수기" in joined:
            ld = _fetch_detail(conn, client, iid, *RULE_PEAK)
        else:
            ld = None
        if ld:
            conn.execute("UPDATE reservation_policies SET lottery_detail=? WHERE instt_id=?", (ld, iid))
        conn.commit()
    return s
