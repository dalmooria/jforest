# jforest/crawlers/forests.py
from jforest.http import BASE
from jforest.db import save_raw
from jforest.parsers.forests import parse_forest_list_json, parse_forest_list_html
from jforest.util import now_iso, Summary

JSON_URL = f"{BASE}/pot/rm/cs/selectInsttHuyangList.do"
HTML_URL = f"{BASE}/pot/is/fs/selectFcltSrchView.do"
MENU_URL = f"{BASE}/com/sub/selectMenuList.do"


def run(conn, client, *, limit=None, force=False) -> Summary:
    s = Summary()
    # --- 1a: 지역별 JSON ---
    for sido in range(1, 10):
        status, body = client.get(JSON_URL, params={"srchSido": sido})
        save_raw(conn, JSON_URL, "forest_list_json", str(sido), status, body, now_iso())
        if status != 200:
            s.failed += 1; s.failures.append(f"sido={sido} HTTP {status}"); continue
        try:
            rows = parse_forest_list_json(body)
        except Exception as e:
            s.failed += 1; s.failures.append(f"sido={sido} parse: {e}"); continue
        for r in rows:
            conn.execute(
                "INSERT OR REPLACE INTO forests "
                "(instt_id, name, sido_code, arcd, instt_type_code, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (r["instt_id"], r["name"], sido, r["arcd"], r["instt_type_code"], now_iso()),
            )
            s.ok += 1
        conn.commit()
        if limit and s.ok >= limit:
            break

    # --- 1b: HTML 목록 전체 페이지 보강 ---
    page = 1
    tot_page = 1
    while page <= tot_page:
        status, body = client.get(HTML_URL, params={"hmpgId": "FRIP", "menuId": "002001", "nowPage": page})
        save_raw(conn, HTML_URL, "forest_list_html", str(page), status, body, now_iso())
        if status != 200:
            break
        if page == 1:
            tot_page = _find_tot_page(body)
        for it in parse_forest_list_html(body):
            conn.execute(
                "UPDATE forests SET instt_type=COALESCE(?, instt_type), "
                "homepage_url=COALESCE(?, homepage_url), tags=COALESCE(?, tags), "
                "summary=COALESCE(?, summary), reservation_intake=COALESCE(?, reservation_intake) "
                "WHERE instt_id=?",
                (it["instt_type"], it["homepage_url"], it["tags"], it["summary"],
                 it["reservation_intake"], it["instt_id"]),
            )
        conn.commit()
        page += 1
        if limit:
            break  # 스모크 모드에서는 1페이지만

    # --- 검증: insttId == hmpgId (표본) ---
    _assert_hmpgid(conn, client)
    return s


def _find_tot_page(body: str) -> int:
    import re
    m = re.search(r"var\s+totPage\s*=\s*(\d+)", body)
    return int(m.group(1)) if m else 1


def _assert_hmpgid(conn, client):
    import json as _json
    row = conn.execute("SELECT instt_id FROM forests LIMIT 1").fetchone()
    if not row:
        return
    iid = row["instt_id"]
    status, body = client.get(MENU_URL, params={"hmpgId": iid})
    # 메뉴 응답이 200이면 insttId가 hmpgId로 동작한다고 간주.
    if status != 200:
        raise AssertionError(
            f"insttId==hmpgId 검증 실패: hmpgId={iid} 메뉴 호출 HTTP {status}. URL 매핑을 재확인하라."
        )
