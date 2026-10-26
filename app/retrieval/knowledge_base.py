"""The saved index (chunks + vectors) and hybrid search over it.

Search combines two rankings with Reciprocal Rank Fusion:
- dense: cosine similarity of embeddings, which handles paraphrases ("price" vs "cost");
- BM25 keywords, which handles exact terms the embeddings blur ("adrenal" vs "anal").
"""

import json
import os
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

from app.ingest.chunker import Chunk
from app.retrieval.embeddings import normalize

RRF_K = 60  # standard Reciprocal Rank Fusion constant

# A question naming one package can still need clinic-wide sections (risks, travel) from
# other pages, so no single page may take all the slots. With top_k=10 this leaves at least
# two slots for other pages while keeping all of a page's cost and inclusion sections.
MAX_PER_PAGE = 8

STOPWORDS = set(
    "a an and are as at be by can do does for from has have how i in is it its me my "
    "of on or the this that to what when where which who will with you your".split()
)


@dataclass
class SearchHit:
    chunk: Chunk
    similarity: float  # cosine similarity between query and chunk embeddings
    score: float  # fused rank score used for ordering


class KnowledgeBase:
    def __init__(
        self,
        chunks: list[Chunk],
        vectors: np.ndarray,
        embed_query: Callable[[str], np.ndarray],
        built_at: str | None = None,
        embedding_model: str | None = None,
    ):
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        if not chunks:
            raise ValueError("the knowledge base is empty")
        self.chunks = chunks
        self.built_at = built_at
        self.embedding_model = embedding_model
        self._vectors = normalize(vectors.astype(np.float32))
        self._embed_query = embed_query
        self._bm25 = BM25Okapi([tokenize(c.search_text) for c in chunks])

    @classmethod
    def load(cls, index_dir: Path, embed_query: Callable[[str], np.ndarray]) -> "KnowledgeBase":
        chunks, vectors, manifest = load_index(index_dir)
        return cls(chunks, vectors, embed_query, built_at=manifest.get("built_at"),
                   embedding_model=manifest.get("embedding_model"))

    def search(self, query: str, top_k: int = 10, min_similarity: float = 0.0,
               max_per_page: int = MAX_PER_PAGE) -> list[SearchHit]:
        """Return the top_k chunks for the query, or [] if nothing is relevant enough."""
        dense = self._vectors @ self._embed_query(query)
        if dense.max() < min_similarity:
            return []

        sparse = self._bm25.get_scores(tokenize(query))
        fused = 1.0 / (RRF_K + _ranks(dense))
        fused += np.where(sparse > 0, 1.0 / (RRF_K + _ranks(sparse)), 0.0)

        hits: list[SearchHit] = []
        per_page: Counter[str] = Counter()
        for i in np.argsort(-fused):
            chunk = self.chunks[i]
            if per_page[chunk.page_id] < max_per_page:
                per_page[chunk.page_id] += 1
                hits.append(SearchHit(chunk, float(dense[i]), float(fused[i])))
                if len(hits) == top_k:
                    break
        return hits


SUFFIXES = ("ations", "ation", "ions", "ion", "ings", "ing", "ies", "ed", "es", "s")


def tokenize(text: str) -> list[str]:
    text = re.sub(r"(?<=\d)[,.](?=\d{3}\b)", "", text.lower())  # "18,995" -> "18995"
    return [_stem(t) for t in re.findall(r"[a-z0-9]+", text) if t not in STOPWORDS]


def _stem(token: str) -> str:
    """Crude suffix stripping so "located"/"location" and "includes"/"included" match."""
    for suffix in SUFFIXES:
        if len(token) - len(suffix) >= 4 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def _ranks(scores: np.ndarray) -> np.ndarray:
    """Rank of each item (1 = best) when sorted by descending score."""
    ranks = np.empty(len(scores), dtype=np.float64)
    ranks[np.argsort(-scores)] = np.arange(1, len(scores) + 1)
    return ranks


# --- index persistence -------------------------------------------------------------

CHUNKS_FILE, VECTORS_FILE, MANIFEST_FILE = "chunks.json", "embeddings.npy", "manifest.json"


def save_index(index_dir: Path, chunks: list[Chunk], vectors: np.ndarray, manifest: dict) -> None:
    """Write the index; each file is written to a temp name first, then swapped in."""
    index_dir.mkdir(parents=True, exist_ok=True)
    manifest = {**manifest, "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "chunk_count": len(chunks)}

    tmp_vectors = index_dir / f"{VECTORS_FILE}.tmp"
    with open(tmp_vectors, "wb") as f:
        np.save(f, vectors.astype(np.float32))
    _write_text(index_dir / f"{CHUNKS_FILE}.tmp",
                json.dumps([c.to_dict() for c in chunks], ensure_ascii=False, indent=1))
    _write_text(index_dir / f"{MANIFEST_FILE}.tmp", json.dumps(manifest, indent=2))

    for name in (VECTORS_FILE, CHUNKS_FILE, MANIFEST_FILE):
        os.replace(index_dir / f"{name}.tmp", index_dir / name)


def load_index(index_dir: Path) -> tuple[list[Chunk], np.ndarray, dict]:
    chunks = [Chunk(**c) for c in json.loads((index_dir / CHUNKS_FILE).read_text(encoding="utf-8"))]
    vectors = np.load(index_dir / VECTORS_FILE)
    manifest = json.loads((index_dir / MANIFEST_FILE).read_text(encoding="utf-8"))
    return chunks, vectors, manifest


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
