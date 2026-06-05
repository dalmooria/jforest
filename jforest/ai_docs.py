from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Iterable

MAX_EMBEDDING_TEXT_CHARS = 3000

# 행정표준코드 시도 prefix (법정동코드 앞 2자리) -> 시도명
_SIDO_BY_ARCD = {
    "11": "서울특별시", "26": "부산광역시", "27": "대구광역시", "28": "인천광역시",
    "29": "광주광역시", "30": "대전광역시", "31": "울산광역시", "36": "세종특별자치시",
    "41": "경기도", "42": "강원도", "43": "충청북도", "44": "충청남도",
    "45": "전라북도", "46": "전라남도", "47": "경상북도", "48": "경상남도",
    "50": "제주특별자치도", "51": "강원특별자치도", "52": "전북특별자치도",
}


def region_from_arcd(arcd: str | None) -> str | None:
    if not arcd:
        return None
    return _SIDO_BY_ARCD.get(str(arcd)[:2])


def forest_prefix(name: str | None, region: str | None) -> str:
    if name and region:
        return f"휴양림: {name} ({region})"
    if name:
        return f"휴양림: {name}"
    return ""


@dataclass(frozen=True)
class EmbeddingDocument:
    doc_id: str
    source_table: str
    source_pk: str
    doc_type: str
    instt_id: str | None
    goods_id: str | None
    title_or_name: str | None
    text: str
    fetched_at: str | None
    updated_at: str | None = None


def _join_text(parts: Iterable[str | None]) -> str:
    return "\n".join(part.strip() for part in parts if part and part.strip())


def _append_document(docs: list[EmbeddingDocument], doc: EmbeddingDocument) -> None:
    if len(doc.text) <= MAX_EMBEDDING_TEXT_CHARS:
        docs.append(doc)
        return

    parts = [
        doc.text[start : start + MAX_EMBEDDING_TEXT_CHARS]
        for start in range(0, len(doc.text), MAX_EMBEDDING_TEXT_CHARS)
    ]
    for index, part in enumerate(parts, start=1):
        docs.append(
            EmbeddingDocument(
                doc_id=f"{doc.doc_id}:part{index}",
                source_table=doc.source_table,
                source_pk=doc.source_pk,
                doc_type=doc.doc_type,
                instt_id=doc.instt_id,
                goods_id=doc.goods_id,
                title_or_name=doc.title_or_name,
                text=part,
                fetched_at=doc.fetched_at,
                updated_at=doc.updated_at,
            )
        )


def save_embedding_documents(docs: list[EmbeddingDocument], path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for doc in docs:
            f.write(json.dumps(asdict(doc), ensure_ascii=False) + "\n")


def load_embedding_documents(path: str) -> list[EmbeddingDocument]:
    docs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                docs.append(EmbeddingDocument(**json.loads(line)))
    return docs


def build_embedding_documents(conn) -> list[EmbeddingDocument]:
    docs: list[EmbeddingDocument] = []

    for row in conn.execute(
        "SELECT instt_id, name, tags, summary, reservation_intake, fetched_at FROM forests ORDER BY instt_id"
    ):
        text = _join_text([row["name"], row["tags"], row["summary"], row["reservation_intake"]])
        if text:
            _append_document(
                docs,
                EmbeddingDocument(
                    doc_id=f"forest:{row['instt_id']}",
                    source_table="forests",
                    source_pk=row["instt_id"],
                    doc_type="forest",
                    instt_id=row["instt_id"],
                    goods_id=None,
                    title_or_name=row["name"],
                    text=text,
                    fetched_at=row["fetched_at"],
                )
            )

    for row in conn.execute(
        "SELECT r.goods_id, r.instt_id, r.name, u.amenities, u.usage_guide, "
        "u.checkin_time, u.checkout_time, u.fetched_at "
        "FROM room_usage_texts u JOIN rooms r ON r.goods_id = u.goods_id ORDER BY r.goods_id"
    ):
        text = _join_text([
            row["name"],
            row["amenities"],
            row["usage_guide"],
            row["checkin_time"],
            row["checkout_time"],
        ])
        if text:
            _append_document(
                docs,
                EmbeddingDocument(
                    doc_id=f"room_usage:{row['goods_id']}",
                    source_table="room_usage_texts",
                    source_pk=row["goods_id"],
                    doc_type="room_usage",
                    instt_id=row["instt_id"],
                    goods_id=row["goods_id"],
                    title_or_name=row["name"],
                    text=text,
                    fetched_at=row["fetched_at"],
                )
            )

    for row in conn.execute(
        "SELECT id, instt_id, target, category, timing, apply_date, room_rates, "
        "campsite_rate, facility_rate, fetched_at FROM discount_policies ORDER BY id"
    ):
        text = _join_text([
            row["target"],
            row["category"],
            row["timing"],
            row["apply_date"],
            row["room_rates"],
            row["campsite_rate"],
            row["facility_rate"],
        ])
        if text:
            _append_document(
                docs,
                EmbeddingDocument(
                    doc_id=f"discount:{row['id']}",
                    source_table="discount_policies",
                    source_pk=str(row["id"]),
                    doc_type="discount",
                    instt_id=row["instt_id"],
                    goods_id=None,
                    title_or_name=row["target"],
                    text=text,
                    fetched_at=row["fetched_at"],
                )
            )

    for row in conn.execute(
        "SELECT instt_id, fcfs_method, lottery_types, priority_types, "
        "fcfs_detail, lottery_detail, fetched_at FROM reservation_policies ORDER BY instt_id"
    ):
        text = _join_text([
            row["fcfs_method"],
            row["lottery_types"],
            row["priority_types"],
            row["fcfs_detail"],
            row["lottery_detail"],
        ])
        if text:
            _append_document(
                docs,
                EmbeddingDocument(
                    doc_id=f"reservation_policy:{row['instt_id']}",
                    source_table="reservation_policies",
                    source_pk=row["instt_id"],
                    doc_type="reservation_policy",
                    instt_id=row["instt_id"],
                    goods_id=None,
                    title_or_name=row["instt_id"],
                    text=text,
                    fetched_at=row["fetched_at"],
                )
            )

    for row in conn.execute(
        "SELECT instt_id, twbbs_id, title, content_text, body_text, updated_at, fetched_at "
        "FROM notices ORDER BY instt_id, twbbs_id"
    ):
        text = _join_text([row["title"], row["content_text"], row["body_text"]])
        if text:
            _append_document(
                docs,
                EmbeddingDocument(
                    doc_id=f"notice:{row['instt_id']}:{row['twbbs_id']}",
                    source_table="notices",
                    source_pk=f"{row['instt_id']}:{row['twbbs_id']}",
                    doc_type="notice",
                    instt_id=row["instt_id"],
                    goods_id=None,
                    title_or_name=row["title"],
                    text=text,
                    fetched_at=row["fetched_at"],
                    updated_at=row["updated_at"],
                )
            )

    for row in conn.execute(
        "SELECT id, instt_id, twbbs_id, file_name, extracted_text, extraction_method, fetched_at "
        "FROM notice_attachments WHERE extracted_text IS NOT NULL AND length(extracted_text) > 0 "
        "ORDER BY instt_id, twbbs_id, id"
    ):
        text = _join_text([row["file_name"], row["extraction_method"], row["extracted_text"]])
        if text:
            _append_document(
                docs,
                EmbeddingDocument(
                    doc_id=f"notice_attachment:{row['id']}",
                    source_table="notice_attachments",
                    source_pk=str(row["id"]),
                    doc_type="notice_attachment",
                    instt_id=row["instt_id"],
                    goods_id=None,
                    title_or_name=row["file_name"],
                    text=text,
                    fetched_at=row["fetched_at"],
                )
            )

    for row in conn.execute(
        "SELECT instt_id, twbbs_id, facts_json, model, needs_review, extracted_at "
        "FROM notice_facts WHERE facts_json IS NOT NULL AND length(facts_json) > 0 "
        "ORDER BY instt_id, twbbs_id"
    ):
        source_pk = f"{row['instt_id']}:{row['twbbs_id']}"
        text = _join_text([row["model"], row["facts_json"], f"needs_review={row['needs_review']}"])
        if text:
            _append_document(
                docs,
                EmbeddingDocument(
                    doc_id=f"notice_fact:{source_pk}",
                    source_table="notice_facts",
                    source_pk=source_pk,
                    doc_type="notice_fact",
                    instt_id=row["instt_id"],
                    goods_id=None,
                    title_or_name=source_pk,
                    text=text,
                    fetched_at=row["extracted_at"],
                )
            )

    return _enrich_with_forest_identity(conn, docs)


# Field-dump doc types whose embedded text lacks any forest identity. Notices,
# forest summaries, and attachments already carry textual context, and enriching
# them floods forest-specific queries with that forest's unrelated docs (measured
# regression), so they are intentionally excluded.
ENRICHED_DOC_TYPES = {"discount", "reservation_policy", "room_usage"}


def _enrich_with_forest_identity(conn, docs: list[EmbeddingDocument]) -> list[EmbeddingDocument]:
    """Prepend '휴양림: <name> (<region>)' to field-dump docs so they carry forest
    identity in their embedded text. These payloads otherwise hold only an opaque
    instt_id, which blocks forest-specific and region-filtered retrieval."""
    forest_meta = {
        row["instt_id"]: (row["name"], region_from_arcd(row["arcd"]))
        for row in conn.execute("SELECT instt_id, name, arcd FROM forests")
    }
    enriched: list[EmbeddingDocument] = []
    for doc in docs:
        meta = forest_meta.get(doc.instt_id)
        if doc.doc_type in ENRICHED_DOC_TYPES and meta and meta[0]:
            prefix = forest_prefix(meta[0], meta[1])
            if prefix and not doc.text.startswith(prefix):
                doc = replace(doc, text=f"{prefix}\n{doc.text}")
        enriched.append(doc)
    return enriched
