# tests/test_crawler_policies.py
import sqlite3, httpx
from pathlib import Path
from jforest.db import init_db
from jforest.http import Client
from jforest.crawlers.policies import run
from jforest.util import now_iso

FX = Path(__file__).parent / "fixtures"

def test_run_matches_and_fills_detail():
    all_body = (FX / "policy_all.html").read_text(encoding="utf-8")
    detail_body = (FX / "policy_detail.html").read_text(encoding="utf-8")
    def handler(request):
        if "selectFripRsrvtPolcyView" in request.url.path:
            return httpx.Response(200, text=all_body)
        if "selectRsrvtGdncView" in request.url.path:
            return httpx.Response(200, text=detail_body)
        return httpx.Response(404)
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row; init_db(conn)
    conn.execute("INSERT INTO forests (instt_id, name, fetched_at) VALUES ('0113','가리왕산',?)", (now_iso(),)); conn.commit()
    client = Client(conn, delay=0, transport=httpx.MockTransport(handler))
    run(conn, client)
    assert conn.execute("SELECT COUNT(*) FROM raw_pages WHERE page_type='policy_all'").fetchone()[0] == 1
    row = conn.execute("SELECT fcfs_detail FROM reservation_policies WHERE instt_id='0113'").fetchone()
    assert row is not None and row["fcfs_detail"] and len(row["fcfs_detail"]) > 20
    detail = conn.execute(
        "SELECT title, detail_text FROM reservation_policy_details "
        "WHERE instt_id='0113' AND rule_id='101'"
    ).fetchone()
    assert detail is not None and detail["title"] and detail["detail_text"]
    # 개별 정책 raw도 복합 ref_key로 저장
    pd = conn.execute("SELECT COUNT(*) FROM raw_pages WHERE page_type='policy_detail' AND ref_key LIKE '0113:%'").fetchone()[0]
    assert pd >= 1
