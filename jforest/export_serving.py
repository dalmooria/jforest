# jforest/export_serving.py
"""웹 서빙용 경량 SQLite 스냅샷을 만든다.

1.3GB 원본(jforest.db)에서 Open Report 웹이 실제로 쓰는 소수 테이블만 뽑아
2MB 안팎의 serving.sqlite로 export한다. Vercel 함수에 번들되어 읽기전용으로 쓰인다.

포함 테이블: forests, reservation_policies, reservation_policy_details,
forest_facilities, (있으면) reservation_blocks.
추가로 serving_meta(generated_at)를 심어 '최종 갱신' 표기에 쓴다.
"""
import os
import sqlite3

from jforest.util import now_iso

SERVING_TABLES = [
    "forests",
    "reservation_policies",
    "reservation_policy_details",
    "forest_facilities",
    "reservation_blocks",  # Phase 2. 없으면 건너뜀.
]


def _table_exists(conn, name: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
    )


def export_serving(src_path: str = "data/jforest.db",
                   dest_path: str = "api/serving.sqlite") -> dict:
    """원본에서 서빙 테이블만 복사한 새 SQLite를 dest_path에 쓴다. 통계 dict 반환."""
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    if os.path.exists(dest_path):
        os.remove(dest_path)

    src = sqlite3.connect(src_path)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(dest_path)
    counts = {}
    try:
        for table in SERVING_TABLES:
            if not _table_exists(src, table):
                continue
            ddl = src.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()[0]
            dst.execute(ddl)
            rows = src.execute(f"SELECT * FROM {table}").fetchall()
            if rows:
                placeholders = ",".join("?" * len(rows[0]))
                dst.executemany(
                    f"INSERT INTO {table} VALUES ({placeholders})",
                    [tuple(r) for r in rows],
                )
            counts[table] = len(rows)
        dst.execute("CREATE TABLE serving_meta (key TEXT PRIMARY KEY, value TEXT)")
        dst.execute(
            "INSERT INTO serving_meta (key, value) VALUES ('generated_at', ?)",
            (now_iso(),),
        )
        dst.commit()
        dst.execute("VACUUM")  # 조각 제거 → 최소 크기
        dst.commit()
    finally:
        src.close()
        dst.close()

    counts["_bytes"] = os.path.getsize(dest_path)
    return counts
