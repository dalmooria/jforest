# jforest/crawlers/policies.py
import json

from jforest.http import BASE
from jforest.db import save_raw
from jforest.parsers.policies import (
    parse_policy_all,
    parse_policy_detail,
    parse_policy_detail_menus,
    parse_policy_detail_title,
    policy_detail_title_or_default,
)
from jforest.util import now_iso, Summary

ALL_URL = f"{BASE}/pot/cc/bb/selectFripRsrvtPolcyView.do"
GDNC_URL = f"{BASE}/pot/rm/ug/selectRsrvtGdncView.do"
# ruleId → (menuId, 용도)
RULE_FCFS = ("101", "004001001")
RULE_WEEKEND = ("102", "004001002")
RULE_PEAK = ("103", "004001003")
RULE_LOCAL_LOTTERY = ("104", "004001004")
RULE_LOCAL_PRIORITY = ("105", "004001005")
RULE_VOUCHER = ("107", "004001007")
RULE_MONTHLY = ("111", "004001011")


def _candidate_rules(row):
    rules = []
    if row["fcfs_method"]:
        rules.append(RULE_FCFS)
    lottery = json.loads(row["lottery_types"]) if row["lottery_types"] else []
    priority = json.loads(row["priority_types"]) if row["priority_types"] else []
    joined_lottery = " ".join(lottery)
    joined_priority = " ".join(priority)
    if "주말" in joined_lottery:
        rules.append(RULE_WEEKEND)
    if "성수기" in joined_lottery:
        rules.append(RULE_PEAK)
    if "지역주민" in joined_lottery:
        rules.append(RULE_LOCAL_LOTTERY)
    if "월" in joined_lottery:
        rules.append(RULE_MONTHLY)
    if "지역주민" in joined_priority:
        rules.append(RULE_LOCAL_PRIORITY)
    if "바우처" in joined_priority:
        rules.append(RULE_VOUCHER)
    return rules or [RULE_FCFS]


def _save_policy_detail(conn, iid, rule, menu, body, fetched_at):
    text = parse_policy_detail(body)
    title = policy_detail_title_or_default(rule, parse_policy_detail_title(body))
    menus = parse_policy_detail_menus(body)
    if title and text:
        conn.execute(
            "INSERT OR REPLACE INTO reservation_policy_details "
            "(instt_id, rule_id, menu_id, title, detail_text, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (iid, rule, menu, title, text, fetched_at),
        )
    return title, text, menus


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
    ts = now_iso()
    save_raw(conn, GDNC_URL, "policy_detail", f"{iid}:{rule}", status, body, ts)
    if status != 200:
        return None
    try:
        title, text, menus = _save_policy_detail(conn, iid, rule, menu, body, ts)
        conn.commit()
        return {"title": title, "text": text, "menus": menus}
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

    # 개별 정책 페이지로 fcfs_detail / lottery_detail 보강 및 전체 상세 정책 저장
    if limit:
        matched = matched[:limit]
    for iid, r in matched:
        queue = list(_candidate_rules(r))
        seen = set()
        details = {}
        while queue:
            rule, menu = queue.pop(0)
            if rule in seen:
                continue
            seen.add(rule)
            detail = _fetch_detail(conn, client, iid, rule, menu)
            if not detail:
                continue
            details[rule] = detail
            for m in detail["menus"]:
                mrule = m["rule_id"]
                mmenu = m["menu_id"]
                if mrule and mmenu and mrule not in seen:
                    queue.append((mrule, mmenu))
        if "101" in details and details["101"]["title"]:
            conn.execute(
                "UPDATE reservation_policies SET fcfs_detail=? WHERE instt_id=?",
                (details["101"]["text"], iid),
            )
        lottery_detail = next(
            (d["text"] for rule, d in details.items()
             if d["title"] and ("추첨" in d["title"] or rule in {"102", "103", "104", "111", "211"})),
            None,
        )
        if lottery_detail:
            conn.execute("UPDATE reservation_policies SET lottery_detail=? WHERE instt_id=?", (lottery_detail, iid))
        conn.commit()
    return s
