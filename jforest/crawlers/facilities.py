# jforest/crawlers/facilities.py
"""휴양림별 공개 정보페이지(자연휴양림안내·프로그램)를 수집한다.

물놀이/숲해설 신호는 이 페이지 본문에 있다(로그인 불필요). 바베큐는 기존
room_detail/공지 데이터에서 뽑으므로 여기서 새로 크롤하지 않는다.

각 휴양림의 메뉴(selectMenuList.do)에서 페이지 URL을 동적으로 찾아 저장한다.
"""
from jforest.http import BASE
from jforest.db import save_raw
from jforest.parsers.facilities import find_info_menu_urls
from jforest.util import now_iso, Summary

MENU_URL = f"{BASE}/com/sub/selectMenuList.do"


def run(conn, client, *, limit=None, force=False) -> Summary:
    s = Summary()
    forests = list(conn.execute("SELECT instt_id FROM forests ORDER BY instt_id"))
    if limit:
        forests = forests[:limit]
    done = set()
    if not force:
        done = {
            r["ref_key"]
            for r in conn.execute(
                "SELECT DISTINCT ref_key FROM raw_pages WHERE page_type='forest_intro'"
            )
        }
    for f in forests:
        iid = f["instt_id"]
        if iid in done:
            s.skipped += 1
            continue
        status, body = client.get(MENU_URL, params={"hmpgId": iid})
        if status != 200:
            s.failed += 1
            s.failures.append(f"{iid} menu HTTP {status}")
            continue
        urls = find_info_menu_urls(body)
        got = False
        for kind, page_type in (("intro", "forest_intro"), ("program", "forest_program")):
            url = urls.get(kind)
            if not url:
                continue
            full = url if url.startswith("http") else BASE + url
            st, pg = client.get(full)
            save_raw(conn, full, page_type, iid, st, pg, now_iso())
            if st == 200:
                got = True
        if got:
            s.ok += 1
        else:
            s.skipped += 1
    return s
