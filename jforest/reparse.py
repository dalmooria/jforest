# jforest/reparse.py
from jforest.db import get_raw_pages
from jforest.parsers.forests import parse_forest_list_json, parse_forest_list_html
from jforest.parsers.rooms import parse_room_list
from jforest.parsers.room_details import parse_room_detail
from jforest.parsers.discounts import parse_discounts
from jforest.parsers.policies import parse_policy_all, parse_policy_detail
from jforest.parsers.notices import parse_notice_detail
from jforest.crawlers.policies import _match_instt
from jforest.util import now_iso

_TABLES = ["forests", "rooms", "room_prices", "room_usage_texts", "discount_policies",
           "reservation_policies", "notices", "notice_attachments", "fetch_log", "raw_pages"]


def status_counts(conn) -> dict:
    out = {}
    for t in _TABLES:
        out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    return out


def reparse(conn, step: str) -> int:
    """raw_pages에서 step 단계 본문을 다시 파싱해 구조화 테이블을 채운다. 처리 건수 반환."""
    n = 0
    if step == "forests":
        for row in get_raw_pages(conn, "forest_list_json"):
            sido = int(row["ref_key"]) if row["ref_key"].isdigit() else None
            for r in parse_forest_list_json(row["body"]):
                conn.execute(
                    "INSERT OR REPLACE INTO forests "
                    "(instt_id, name, sido_code, arcd, instt_type_code, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (r["instt_id"], r["name"], sido, r["arcd"], r["instt_type_code"], now_iso()),
                )
                n += 1
        for row in get_raw_pages(conn, "forest_list_html"):
            for it in parse_forest_list_html(row["body"]):
                conn.execute(
                    "UPDATE forests SET instt_type=COALESCE(?, instt_type), "
                    "homepage_url=COALESCE(?, homepage_url), tags=COALESCE(?, tags), "
                    "summary=COALESCE(?, summary), reservation_intake=COALESCE(?, reservation_intake) "
                    "WHERE instt_id=?",
                    (it["instt_type"], it["homepage_url"], it["tags"], it["summary"],
                     it["reservation_intake"], it["instt_id"]),
                )
    elif step == "rooms":
        for row in get_raw_pages(conn, "room_list"):
            iid = row["ref_key"]
            for r in parse_room_list(row["body"]):
                conn.execute(
                    "INSERT OR REPLACE INTO rooms "
                    "(goods_id, instt_id, room_type, name, capacity_standard, capacity_max, area, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (r["goods_id"], iid, r["room_type"], r["name"],
                     r["capacity_standard"], r["capacity_max"], r["area"], now_iso()),
                )
                n += 1
    elif step == "room-details":
        for row in get_raw_pages(conn, "room_detail"):
            gid = row["ref_key"]
            d = parse_room_detail(row["body"])
            conn.execute("DELETE FROM room_prices WHERE goods_id=?", (gid,))
            for p in d["prices"]:
                conn.execute(
                    "INSERT INTO room_prices (goods_id, season, day_type, raw_label, price, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (gid, p["season"], p["day_type"], p["raw_label"], p["price"], now_iso()),
                )
            conn.execute(
                "INSERT OR REPLACE INTO room_usage_texts "
                "(goods_id, checkin_time, checkout_time, amenities, usage_guide, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (gid, d["checkin_time"], d["checkout_time"], d["amenities"], d["usage_guide"], now_iso()),
            )
            n += 1
    elif step == "discounts":
        for row in get_raw_pages(conn, "discount"):
            iid = row["ref_key"]
            conn.execute("DELETE FROM discount_policies WHERE instt_id=?", (iid,))
            for r in parse_discounts(row["body"]):
                conn.execute(
                    "INSERT INTO discount_policies "
                    "(instt_id, target, category, timing, apply_date, room_rates, campsite_rate, facility_rate, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (iid, r["target"], r["category"], r["timing"], r["apply_date"],
                     r["room_rates"], r["campsite_rate"], r["facility_rate"], now_iso()),
                )
                n += 1
    elif step == "notices":
        for row in get_raw_pages(conn, "notice_detail"):
            iid, twbbs = row["ref_key"].split(":", 1)
            d = parse_notice_detail(row["body"])
            conn.execute(
                "INSERT OR REPLACE INTO notices (instt_id, twbbs_id, title, updated_at, body_text, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (iid, twbbs, d["title"], d["updated_at"], d["body_text"], now_iso()),
            )
            for a in d["attachments"]:
                conn.execute(
                    "INSERT OR REPLACE INTO notice_attachments "
                    "(instt_id, twbbs_id, file_master_id, file_id, file_name, content_type, local_path, downloaded, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, NULL, NULL, 0, ?)",
                    (iid, twbbs, a["file_master_id"], a["file_id"], a.get("file_name"), now_iso()),
                )
            n += 1
    elif step == "policies":
        forests = list(conn.execute("SELECT instt_id, name FROM forests"))
        for row in get_raw_pages(conn, "policy_all"):
            for r in parse_policy_all(row["body"]):
                iid = _match_instt(forests, r["name"])
                if not iid:
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO reservation_policies "
                    "(instt_id, operates_rooms, operates_campsite, operates_waitlist, "
                    "fcfs_method, lottery_types, priority_types, fcfs_detail, lottery_detail, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, "
                    "(SELECT fcfs_detail FROM reservation_policies WHERE instt_id=?), "
                    "(SELECT lottery_detail FROM reservation_policies WHERE instt_id=?), ?)",
                    (iid, r["operates_rooms"], r["operates_campsite"], r["operates_waitlist"],
                     r["fcfs_method"], r["lottery_types"], r["priority_types"], iid, iid, now_iso()),
                )
                n += 1
        for row in get_raw_pages(conn, "policy_detail"):
            iid, rule = row["ref_key"].split(":", 1)
            txt = parse_policy_detail(row["body"])
            col = "fcfs_detail" if rule == "101" else "lottery_detail"
            conn.execute(f"UPDATE reservation_policies SET {col}=? WHERE instt_id=?", (txt, iid))
    else:
        raise ValueError(f"reparse 미지원 단계: {step}")
    conn.commit()
    return n
