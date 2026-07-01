# tests/test_api_open_report.py
import importlib
import sqlite3

import pytest
from fastapi.testclient import TestClient

from jforest.db import init_db
from jforest.util import now_iso


@pytest.fixture
def client(tmp_path, monkeypatch):
    """임시 serving.sqlite를 만들고 api.index가 그것을 읽도록 한다."""
    db = tmp_path / "serving.sqlite"
    conn = sqlite3.connect(db)
    init_db(conn)
    conn.execute("INSERT INTO forests (instt_id,name,sido_code,fetched_at) VALUES ('0101','수요일휴양림',3,?)", (now_iso(),))
    conn.execute("INSERT INTO reservation_policies (instt_id,fcfs_method,fcfs_detail,fetched_at) VALUES ('0101','6주 수요일','매주 수요일 오전 9시',?)", (now_iso(),))
    conn.execute("INSERT INTO forests (instt_id,name,sido_code,fetched_at) VALUES ('0102','추첨휴양림',2,?)", (now_iso(),))
    conn.execute("INSERT INTO reservation_policy_details (instt_id,rule_id,title,detail_text,fetched_at) VALUES ('0102','102','주말추첨제','○ 신청 접수 기간\n매월 4일 오전 9시',?)", (now_iso(),))
    conn.execute("CREATE TABLE serving_meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO serving_meta VALUES ('generated_at','2026-07-01T00:00:00Z')")
    conn.commit(); conn.close()

    import api.index as idx
    importlib.reload(idx)
    monkeypatch.setattr(idx, "SERVING_DB", str(db))
    return TestClient(idx.app)


def test_open_page_serves_html(client):
    r = client.get("/open")
    assert r.status_code == 200 and "예약오픈" in r.text and "viewport" in r.text


def test_open_report_wednesday(client):
    r = client.get("/api/open-report?date=2026-07-01")  # 수
    assert r.status_code == 200
    j = r.json()
    assert j["date"] == "2026-07-01" and j["weekday"] == "수"
    assert any(g["type_group"] == "선착순" for g in j["groups"])
    assert j["generated_at"] == "2026-07-01T00:00:00Z"


def test_open_report_saturday_lottery(client):
    j = client.get("/api/open-report?date=2026-07-04").json()  # 토, 매월 4일
    assert any(g["type_group"] == "추첨" for g in j["groups"])


def test_bad_date_returns_400(client):
    assert client.get("/api/open-report?date=2026-13-99").status_code == 400
    assert client.get("/api/open-report?date=oops").status_code == 400


def test_region_filter(client):
    j = client.get("/api/open-report?date=2026-07-04&region=경기·인천").json()
    # 추첨휴양림은 강원(2)이므로 경기 필터 시 제외
    assert j["total"] == 0


def test_health(client):
    assert client.get("/api/health").json()["ok"] is True
