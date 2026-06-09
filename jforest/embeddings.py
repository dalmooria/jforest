from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol


@dataclass(frozen=True)
class EmbeddingCandidate:
    name: str
    dimension: int
    provider: str
    model: str


CANDIDATES = {
    "openai-small": EmbeddingCandidate("openai-small", 1536, "openai", "text-embedding-3-small"),
    "openai-large": EmbeddingCandidate("openai-large", 3072, "openai", "text-embedding-3-large"),
    "bge-m3": EmbeddingCandidate("bge-m3", 1024, "sentence-transformers", "BAAI/bge-m3"),
}


class Embedder(Protocol):
    candidate: EmbeddingCandidate

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


class OpenAIEmbedder:
    def __init__(self, candidate: EmbeddingCandidate):
        from openai import OpenAI

        self.candidate = candidate
        self.client = OpenAI(timeout=120.0)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        response = self.client.embeddings.create(model=self.candidate.model, input=texts)
        return [item.embedding for item in response.data]


class SentenceTransformerEmbedder:
    def __init__(self, candidate: EmbeddingCandidate):
        self.candidate = candidate
        self.model = _load_sentence_transformer(candidate.model)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(texts, normalize_embeddings=True)
        return [vector.tolist() for vector in vectors]


@lru_cache(maxsize=1)
def _load_sentence_transformer(model_name: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


def get_embedder(candidate_name: str) -> Embedder:
    if candidate_name not in CANDIDATES:
        choices = ", ".join(sorted(CANDIDATES))
        raise ValueError(f"unknown embedding candidate: {candidate_name}. Choices: {choices}")
    candidate = CANDIDATES[candidate_name]
    if candidate.provider == "openai":
        return OpenAIEmbedder(candidate)
    return SentenceTransformerEmbedder(candidate)
