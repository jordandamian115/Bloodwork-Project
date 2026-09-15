"""Ollama embeddings that stay within the Windows runner's limits."""

from __future__ import annotations

import time

from langchain_core.embeddings import Embeddings
from langchain_ollama import OllamaEmbeddings

MAX_CHARS = 1800
BATCH_SIZE = 2
RETRIES = 6


class SafeOllamaEmbeddings(Embeddings):
    def __init__(self, model: str) -> None:
        self._model = model
        self._inner = OllamaEmbeddings(model=model)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        clipped = [(text or " ")[:MAX_CHARS] for text in texts]
        for start in range(0, len(clipped), BATCH_SIZE):
            batch = clipped[start : start + BATCH_SIZE]
            vectors.extend(self._embed_batch(batch))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed_batch([(text or " ")[:MAX_CHARS]])[0]

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        last_error: Exception | None = None
        for attempt in range(RETRIES):
            try:
                if len(batch) == 1:
                    return [self._inner.embed_query(batch[0])]
                return self._inner.embed_documents(batch)
            except Exception as exc:
                last_error = exc
                message = str(exc).lower()
                fragile = (
                    "tokenize" in message
                    or "refused" in message
                    or "status code: 400" in message
                    or "eof" in message
                )
                if not fragile:
                    raise
                time.sleep(1.5 * (attempt + 1))
                if len(batch) > 1:
                    pieces: list[list[float]] = []
                    for item in batch:
                        pieces.extend(self._embed_batch([item]))
                    return pieces
        raise RuntimeError(
            "Ollama's embedding runner died while tokenizing "
            f"({self._model}). Restart the Ollama app, then retry. Last error: {last_error}"
        ) from last_error
