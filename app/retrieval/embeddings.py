"""OpenAI embeddings, returned as unit-length vectors so a dot product is cosine similarity."""

import numpy as np
from openai import OpenAI


class Embedder:
    def __init__(self, client: OpenAI, model: str, batch_size: int = 64):
        self._client = client
        self.model = model
        self.batch_size = batch_size

    def embed(self, texts: list[str]) -> np.ndarray:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            response = self._client.embeddings.create(
                model=self.model, input=texts[start : start + self.batch_size]
            )
            vectors.extend(item.embedding for item in response.data)
        return normalize(np.array(vectors, dtype=np.float32))

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed([text])[0]


def normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    return vectors / np.where(norms == 0, 1, norms)
