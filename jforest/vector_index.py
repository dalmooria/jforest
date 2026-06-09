from __future__ import annotations

import hashlib
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from jforest.ai_docs import EmbeddingDocument


def stable_point_id(doc_id: str) -> int:
    digest = hashlib.sha256(doc_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


class QdrantLocalIndex:
    def __init__(self, root: str, collection: str, dimension: int):
        Path(root).mkdir(parents=True, exist_ok=True)
        self.client = QdrantClient(path=root)
        self.collection = collection
        self.dimension = dimension

    def recreate(self) -> None:
        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=VectorParams(size=self.dimension, distance=Distance.COSINE),
        )

    def upsert(self, docs: list[EmbeddingDocument], vectors: list[list[float]]) -> None:
        points = []
        for doc, vector in zip(docs, vectors, strict=True):
            points.append(
                PointStruct(
                    id=stable_point_id(doc.doc_id),
                    vector=vector,
                    payload={
                        "doc_id": doc.doc_id,
                        "source_table": doc.source_table,
                        "source_pk": doc.source_pk,
                        "doc_type": doc.doc_type,
                        "instt_id": doc.instt_id,
                        "goods_id": doc.goods_id,
                        "title_or_name": doc.title_or_name,
                        "text": doc.text[:1200],
                        "fetched_at": doc.fetched_at,
                        "updated_at": doc.updated_at,
                    },
                )
            )
        self.client.upsert(collection_name=self.collection, points=points)

    def search(self, vector: list[float], limit: int) -> list[dict]:
        hits = self.client.query_points(
            collection_name=self.collection,
            query=vector,
            limit=limit,
            with_payload=True,
        ).points
        results = []
        for hit in hits:
            payload = dict(hit.payload or {})
            payload["score"] = hit.score
            results.append(payload)
        return results
