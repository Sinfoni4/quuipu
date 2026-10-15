"""Calcolo dei vettori (embedding) per la ricerca per significato.

Come per i modelli linguistici, il resto del codice dipende solo dal
protocollo Embedder. Il modello predefinito è mistral-embed, modificabile
con QUUIPU_EMBED_MODEL.
"""

from __future__ import annotations

import os
from typing import Protocol, Sequence

import httpx
from dotenv import load_dotenv

from quuipu.ingestion.llm import LLMError

BATCH_SIZE = 32


class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Un vettore per ogni testo, nello stesso ordine."""
        ...


class MistralEmbedder:
    API_URL = "https://api.mistral.ai/v1/embeddings"

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        http: httpx.Client | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("MISTRAL_API_KEY", "")
        if not self.api_key:
            raise LLMError("manca MISTRAL_API_KEY")
        self.http = http or httpx.Client(timeout=timeout)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = list(texts[start:start + BATCH_SIZE])
            try:
                response = self.http.post(
                    self.API_URL,
                    json={"model": self.model, "input": batch},
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                response.raise_for_status()
                data = sorted(response.json()["data"], key=lambda d: d["index"])
                vectors.extend(d["embedding"] for d in data)
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                raise LLMError(f"embedding non riuscito: {exc}") from exc
        if len(vectors) != len(texts):
            raise LLMError("numero di vettori diverso dal numero di testi")
        return vectors


def default_embedder() -> Embedder:
    load_dotenv()
    return MistralEmbedder(os.environ.get("QUUIPU_EMBED_MODEL", "mistral-embed"))
