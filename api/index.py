"""Vercel serverless 진입점 (ASGI).

⚠ 의도적으로 경량: `jforest.rag`(torch/qdrant/sentence-transformers)를 절대 import하지 않는다.
   → 함수 번들이 Vercel 250MB 한도 안에 들어온다.

읽기 데이터는 번들된 `api/serving.sqlite`(약 2MB, 읽기전용). 로컬 파이프라인이
`jforest export-serving`으로 매일 갱신 → git push → Vercel 자동 재배포한다.

현재는 배포 파이프라인 검증용 스켈레톤(/api/health). Phase 1에서 `/open`·`/api/open-report`를
`jforest.fcfs_report.build_open_events`로 채운다(설계서 §10 참조).
"""
import os
import sqlite3

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

SERVING_DB = os.path.join(os.path.dirname(__file__), "serving.sqlite")

app = FastAPI(title="jforest open-report")


def _conn() -> sqlite3.Connection:
    if not os.path.exists(SERVING_DB):
        raise HTTPException(503, "serving.sqlite 미배포 — 로컬 파이프라인의 export-serving 필요")
    conn = sqlite3.connect(f"file:{SERVING_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/api/health")
def health() -> dict:
    """번들된 serving.sqlite가 함수에서 읽히는지 확인(배포 검증용)."""
    conn = _conn()
    try:
        gen = conn.execute(
            "SELECT value FROM serving_meta WHERE key='generated_at'"
        ).fetchone()
        counts = {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("forests", "reservation_policies", "reservation_policy_details")
        }
        return {"ok": True, "generated_at": gen[0] if gen else None, "counts": counts}
    finally:
        conn.close()


@app.get("/open", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (
        "<!DOCTYPE html><html lang=ko><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width, initial-scale=1'>"
        "<title>휴양림 예약오픈</title></head><body style='font-family:system-ui;"
        "max-width:640px;margin:0 auto;padding:24px'>"
        "<h1>🌲 날짜별 예약오픈 안내</h1>"
        "<p>배포 파이프라인 준비 완료. Phase 1에서 날짜 선택 UI가 채워집니다.</p>"
        "<p><a href='/api/health'>/api/health</a></p></body></html>"
    )
