# tests/test_crawler_facilities.py
import sqlite3
import httpx

from jforest.db import init_db
from jforest.http import Client
from jforest.crawlers.facilities import run
from jforest.util import now_iso

MENU = """{"menuList":[
  {"menuNm":"자연휴양림안내","menuUrl":"/pot/rm/ri/selectRcrfrIntrdDtlView.do?hmpgId=0101&menuId=002001"},
  {"menuNm":"프로그램","menuUrl":"/pot/rm/fa/selectPrgrmListView.do?hmpgId=0101&menuId=002003"}
]}"""
INTRO = "<html><body>맑은 계곡에서 물놀이가 가능합니다.</body></html>"
PROGRAM = "<html><body>숲해설 프로그램 운영기간 3월~12월</body></html>"


def _handler(request):
    p = request.url.path
    if "selectMenuList" in p:
        return httpx.Response(200, text=MENU)
    if "selectRcrfrIntrdDtlView" in p:
        return httpx.Response(200, text=INTRO)
    if "selectPrgrmListView" in p:
        return httpx.Response(200, text=PROGRAM)
    return httpx.Response(404)


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    conn.execute("INSERT INTO forests (instt_id, name, fetched_at) VALUES ('0101','유명산',?)", (now_iso(),))
    conn.commit()
    return conn


def test_run_saves_intro_and_program_pages():
    conn = _conn()
    client = Client(conn, delay=0, transport=httpx.MockTransport(_handler))
    s = run(conn, client)
    assert s.ok == 1
    intro = conn.execute("SELECT body FROM raw_pages WHERE page_type='forest_intro' AND ref_key='0101'").fetchone()
    prog = conn.execute("SELECT body FROM raw_pages WHERE page_type='forest_program' AND ref_key='0101'").fetchone()
    assert intro and "물놀이" in intro["body"]
    assert prog and "숲해설" in prog["body"]


def test_run_skips_already_collected_unless_force():
    conn = _conn()
    client = Client(conn, delay=0, transport=httpx.MockTransport(_handler))
    run(conn, client)
    s2 = run(conn, client)
    assert s2.skipped == 1 and s2.ok == 0
    s3 = run(conn, client, force=True)
    assert s3.ok == 1
