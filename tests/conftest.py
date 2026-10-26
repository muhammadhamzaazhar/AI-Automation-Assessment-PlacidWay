"""Shared test helpers. Tests never call OpenAI or the network: these fakes stand in."""

import hashlib
import re

import numpy as np
import pytest

from app.chat.llm import LLMError
from app.ingest.chunker import Chunk
from app.retrieval.knowledge_base import KnowledgeBase, SearchHit


def make_chunk(page_id: str, text: str, n: int = 1, title: str | None = None) -> Chunk:
    return Chunk(
        id=f"{page_id}#{n}",
        page_id=page_id,
        url=f"https://example.com/{page_id}",
        page_title=title or page_id.replace("-", " ").title(),
        page_type="treatment package",
        section="Section",
        text=text,
    )


def fake_embed(text: str, dims: int = 256) -> np.ndarray:
    """Deterministic bag-of-words vector: texts sharing words get similar vectors."""
    vector = np.zeros(dims, dtype=np.float32)
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % dims] += 1.0
    norm = np.linalg.norm(vector)
    return vector / norm if norm else vector


def make_kb(chunks: list[Chunk]) -> KnowledgeBase:
    vectors = np.stack([fake_embed(c.search_text) for c in chunks])
    return KnowledgeBase(chunks, vectors, fake_embed, embedding_model="fake")


class FakeLLM:
    """Returns queued results in order; an Exception in the queue is raised instead."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls: list[tuple[str, str]] = []
        self.translations = 0

    def parse(self, instructions, prompt, schema):
        self.calls.append((instructions, prompt))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def complete(self, instructions, prompt):
        self.translations += 1
        return f"[translated] {prompt}"


class FakeKB:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.built_at = "test"
        self.queries: list[str] = []

    def search(self, query, top_k=6, min_similarity=0.0):
        self.queries.append(query)
        return [SearchHit(c, 0.9, 1.0) for c in self.chunks[:top_k]]


@pytest.fixture
def llm_error():
    return LLMError("simulated outage")
