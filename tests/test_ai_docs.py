import sqlite3

from jforest.ai_docs import (
    EmbeddingDocument,
    MAX_EMBEDDING_TEXT_CHARS,
    build_embedding_documents,
    load_embedding_documents,
    save_embedding_documents,
)
from jforest.db import init_db


def test_build_embedding_documents_includes_room_usage_notice_attachment_and_facts():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    conn.execute(
        "INSERT INTO forests (instt_id, name, tags, summary, reservation_intake, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("F1", "가리산자연휴양림", '["계곡"]', "계곡과 산책로가 있다", "선착순", "2026-06-04T00:00:00"),
    )
    conn.execute(
        "INSERT INTO rooms (goods_id, instt_id, name, fetched_at) VALUES (?, ?, ?, ?)",
        ("G1", "F1", "숲속의집 101호", "2026-06-04T00:00:00"),
    )
    conn.execute(
        "INSERT INTO room_usage_texts (goods_id, amenities, usage_guide, fetched_at) VALUES (?, ?, ?, ?)",
        ("G1", "바베큐장, 계곡", "여름철 물놀이 가능", "2026-06-04T00:00:00"),
    )
    conn.execute(
        "INSERT INTO notices (instt_id, twbbs_id, title, body_text, content_text, updated_at, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "F1",
            "N1",
            "물놀이장 운영 안내",
            "본문 전체",
            "7월부터 물놀이장을 운영합니다.",
            "2026-06-01",
            "2026-06-04T00:00:00",
        ),
    )
    conn.execute(
        "INSERT INTO notice_attachments "
        "(instt_id, twbbs_id, file_master_id, file_id, file_name, extracted_text, extraction_method, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "F1",
            "N1",
            "FM1",
            "FILE1",
            "물놀이장 안내문.pdf",
            "어린이 물놀이장 이용시간 안내",
            "pdftext",
            "2026-06-04T00:00:00",
        ),
    )
    conn.execute(
        "INSERT INTO notice_facts (instt_id, twbbs_id, facts_json, model, extracted_at) VALUES (?, ?, ?, ?, ?)",
        ("F1", "N1", '{"waterPlay":"7월부터 물놀이장 운영"}', "gemini-test", "2026-06-04T00:00:00"),
    )
    conn.commit()

    docs = build_embedding_documents(conn)

    doc_ids = {doc.doc_id for doc in docs}
    assert "forest:F1" in doc_ids
    assert "room_usage:G1" in doc_ids
    assert "notice:F1:N1" in doc_ids
    assert "notice_attachment:1" in doc_ids
    assert "notice_fact:F1:N1" in doc_ids
    notice = next(doc for doc in docs if doc.doc_id == "notice:F1:N1")
    assert notice.instt_id == "F1"
    assert "7월부터 물놀이장을 운영합니다." in notice.text
    assert notice.source_table == "notices"


def test_build_embedding_documents_splits_long_attachment_text():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    conn.execute(
        "INSERT INTO notice_attachments "
        "(instt_id, twbbs_id, file_master_id, file_id, file_name, extracted_text, extraction_method, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "F1",
            "N1",
            "FM1",
            "FILE1",
            "긴 첨부.pdf",
            "가" * (MAX_EMBEDDING_TEXT_CHARS + 100),
            "pdftext",
            "2026-06-04T00:00:00",
        ),
    )
    conn.commit()

    docs = [doc for doc in build_embedding_documents(conn) if doc.doc_type == "notice_attachment"]

    assert len(docs) == 2
    assert docs[0].doc_id == "notice_attachment:1:part1"
    assert docs[1].doc_id == "notice_attachment:1:part2"
    assert all(len(doc.text) <= MAX_EMBEDDING_TEXT_CHARS for doc in docs)
    assert all(doc.source_pk == "1" for doc in docs)


def test_save_and_load_embedding_documents_round_trips(tmp_path):
    path = tmp_path / "corpus.jsonl"
    docs = [
        EmbeddingDocument(
            doc_id="notice:F1:N1",
            source_table="notices",
            source_pk="F1:N1",
            doc_type="notice",
            instt_id="F1",
            goods_id=None,
            title_or_name="공지",
            text="물놀이장 운영 안내",
            fetched_at="2026-06-04T00:00:00",
            updated_at="2026-06-01",
        )
    ]

    save_embedding_documents(docs, str(path))
    loaded = load_embedding_documents(str(path))

    assert loaded == docs


def test_region_from_arcd_maps_standard_prefixes():
    from jforest.ai_docs import region_from_arcd

    assert region_from_arcd("41820") == "경기도"
    assert region_from_arcd("28710") == "인천광역시"
    assert region_from_arcd("48125") == "경상남도"
    assert region_from_arcd(None) is None
    assert region_from_arcd("99999") is None


def test_build_embedding_documents_enriches_discount_with_forest_name_and_region():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    conn.execute(
        "INSERT INTO forests (instt_id, name, arcd, fetched_at) VALUES (?, ?, ?, ?)",
        ("F1", "산삼자연휴양림", "48125", "2026-06-04T00:00:00"),
    )
    conn.execute(
        "INSERT INTO discount_policies (id, instt_id, target, category, timing, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (1, "F1", "장애인(등급 : 1급 ~ 6급)", "정율", "결제시할인", "2026-06-04T00:00:00"),
    )
    conn.commit()

    docs = build_embedding_documents(conn)
    discount = next(doc for doc in docs if doc.doc_type == "discount")

    # forest identity is now part of the embedded text (fixes retrieval name gap)
    assert "산삼자연휴양림" in discount.text
    assert "경상남도" in discount.text
    # original field content preserved
    assert "장애인(등급 : 1급 ~ 6급)" in discount.text
