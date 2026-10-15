"""Oggetti di prova condivisi tra i test."""

import hashlib
import re

from quuipu.config import ClientConfig, CrawlSettings, IngestionSettings
from quuipu.demo.files import make_pdf
from quuipu.ingestion.llm import LLMError


class FakeLLM:
    """Restituisce risposte preparate in ordine e registra le chiamate."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def complete_json(self, system, user, images=()):
        self.calls.append({"system": system, "user": user, "images": list(images)})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeEmbedder:
    """Vettori per parole: testi con parole in comune risultano vicini."""

    DIMENSIONS = 64

    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        vectors = []
        for text in texts:
            vector = [0.0] * self.DIMENSIONS
            for word in re.findall(r"\w+", text.lower()):
                bucket = int(hashlib.md5(word.encode()).hexdigest(), 16) % self.DIMENSIONS
                vector[bucket] += 1.0
            vectors.append(vector)
        return vectors


def wine_client(**ingestion):
    return ClientConfig(
        id="cantina",
        name="Cantina di prova",
        sector="agrifood",
        base_url="https://www.cantina.test/",
        languages=("it", "en"),
        crawl=CrawlSettings(delay_seconds=0),
        ingestion=IngestionSettings(
            image_categories=("bottiglia", "vigneto", "cantina", "altro"), **ingestion
        ),
    )


__all__ = ["FakeEmbedder", "FakeLLM", "LLMError", "make_pdf", "wine_client"]
