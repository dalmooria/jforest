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


def test_match_instt_prefers_exact_over_substring():
    """이름 충돌 시 정규화 완전일치를 부분매칭보다 우선한다.

    '광양백운산자연휴양림'이 '백운산 자연휴양림'에 부분매칭되어 엉뚱한 iid로
    라우팅되던 회귀 버그를 막는다.
    """
    from jforest.crawlers.policies import _match_instt

    forests = [
        {"instt_id": "0223", "name": "백운산 자연휴양림"},
        {"instt_id": "ID02030061", "name": "광양백운산자연휴양림"},
    ]
    # 완전일치가 있으면 그것을 반환 (부분매칭 0223로 새지 않음)
    assert _match_instt(forests, "광양백운산자연휴양림") == "ID02030061"
    assert _match_instt(forests, "백운산 자연휴양림") == "0223"
    # 완전일치가 없으면 부분매칭 폴백 유지 (변형 메뉴명 대응)
    assert _match_instt(forests, "백운산 자연휴양림 물놀이장") == "0223"
