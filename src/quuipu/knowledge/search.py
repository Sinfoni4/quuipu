"""Indicizzazione e ricerca semantica nella base di conoscenza.

La ricerca restituisce solo contenuti approvati (salvo richiesta diversa):
l'agente non deve mai vedere ciò che è in revisione o escluso.
Per il PoC la similarità si calcola in Python; con pgvector passerà al database.
"""

from __future__ import annotations

import math
import re

from quuipu.knowledge.embeddings import Embedder
from quuipu.knowledge.store import APPROVED, KnowledgeStore

MAX_CHUNK_CHARS = 800


def chunk_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Divide il testo in pezzi di circa max_chars, senza spezzare le righe se possibile."""
    chunks: list[str] = []
    current = ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        while len(line) > max_chars:
            cut = line.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:cut].strip())
            line = line[cut:].strip()
        if current and len(current) + len(line) + 1 > max_chars:
            chunks.append(current)
            current = ""
        current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


def content_chunks(content: dict) -> list[str]:
    """Pezzi da indicizzare; ognuno porta il titolo per non perdere il contesto."""
    title = content["titolo"]
    pieces = chunk_text(content["testo"]) or ([title] if title else [])
    return [f"{title}\n{p}" if title and p != title else p for p in pieces]


def index_contents(store: KnowledgeStore, embedder: Embedder) -> int:
    """Calcola i vettori dei contenuti nuovi o cambiati; restituisce quanti ne ha elaborati."""
    pending = [(c, content_chunks(c)) for c in store.contents_to_index()]
    texts = [text for _, chunks in pending for text in chunks]
    vectors = embedder.embed(texts) if texts else []
    position = 0
    for content, chunks in pending:
        store.replace_chunks(
            content["id"], content["hash"],
            list(zip(chunks, vectors[position:position + len(chunks)])),
        )
        position += len(chunks)
    return len(pending)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def search(
    store: KnowledgeStore,
    embedder: Embedder,
    query: str,
    k: int = 5,
    profilo: str | None = None,
    tipo: str | None = None,
    lingua: str | None = None,
    stati: tuple[str, ...] = (APPROVED,),
) -> list[dict]:
    """I k contenuti più vicini alla domanda, con il pezzo di testo più pertinente."""
    if not re.search(r"\w", query):
        return []
    query_vector = embedder.embed([query])[0]
    best: dict[str, tuple[float, str]] = {}
    for chunk in store.chunks(stati):
        score = cosine(query_vector, chunk["vettore"])
        if chunk["content_id"] not in best or score > best[chunk["content_id"]][0]:
            best[chunk["content_id"]] = (score, chunk["testo"])

    results: list[dict] = []
    for content_id, (score, snippet) in sorted(best.items(), key=lambda kv: -kv[1][0]):
        content = store.get(content_id)
        if content is None:
            continue
        if profilo and profilo not in content["profili"]:
            continue
        if tipo and content["tipo"] != tipo:
            continue
        if lingua and content["lingua"] and content["lingua"] != lingua:
            continue
        results.append({"contenuto": content, "punteggio": round(score, 4), "estratto": snippet})
        if len(results) == k:
            break
    return results
