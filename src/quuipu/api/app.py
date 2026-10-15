"""API FastAPI della piattaforma (specifica §3, §6, §10, §13).

Endpoint:
- GET  /health: stato del servizio.
- POST /v1/{cliente}/plan: riceve il contesto della visita, stima il profilo,
  restituisce il page plan validato con i dati dei contenuti, oppure
  {"standard": true} e il sito resta com'è.
- GET  /v1/{cliente}/contents/{id}: dati pubblici di un contenuto approvato.
- GET  /v1/{cliente}/status: se l'agente del cliente è acceso.

I motori di ricerca ricevono sempre la pagina standard (§13).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from quuipu.api.render import approved_content, resolve_plan
from quuipu.api.sessions import SessionStore
from quuipu.composer.planner import Planner, PlanRequest
from quuipu.config import CLIENTS_DIR, ClientConfig, data_dir, load_client
from quuipu.control import agent_status
from quuipu.ingestion.llm import LLMClient, LLMError, text_client
from quuipu.knowledge.embeddings import Embedder, default_embedder
from quuipu.knowledge.store import KnowledgeStore
from quuipu.visitor.profile import estimate_profile

CLIENT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
BOT_USER_AGENT = re.compile(
    r"bot|crawl|spider|slurp|bingpreview|facebookexternalhit|embedly|lighthouse|headless|preview",
    re.IGNORECASE,
)
MAX_TEXT = 2000


class PlanBody(BaseModel):
    session_id: str | None = Field(default=None, max_length=64)
    pagina: str = Field(max_length=MAX_TEXT)
    referrer: str = Field(default="", max_length=MAX_TEXT)
    lingua: str = Field(default="", max_length=35)
    dispositivo: str = Field(default="", max_length=20)
    domanda: str | None = Field(default=None, max_length=MAX_TEXT)


def is_bot(user_agent: str) -> bool:
    return bool(BOT_USER_AGENT.search(user_agent or ""))


def _optional(factory: Callable):
    try:
        return factory()
    except LLMError:
        return None


def create_app(
    *,
    clients_dir: Path | None = None,
    data_root: Path | None = None,
    llm_factory: Callable[[], LLMClient] = text_client,
    embedder_factory: Callable[[], Embedder] = default_embedder,
    sessions: SessionStore | None = None,
) -> FastAPI:
    clients_dir = clients_dir or CLIENTS_DIR
    data_root = data_root or data_dir()
    sessions = sessions or SessionStore()
    app = FastAPI(title="Quuipu", version="0.1.0")

    # CORS: solo i siti dichiarati dai clienti (più eventuali origini di sviluppo).
    origins = set(filter(None, os.environ.get("QUUIPU_EXTRA_ORIGINS", "").split(",")))
    for path in clients_dir.glob("*.toml"):
        origins.update(load_client(path.stem, clients_dir).allowed_origins)
    app.add_middleware(
        CORSMiddleware, allow_origins=sorted(origins), allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    models: dict[str, object] = {}

    def llm() -> LLMClient | None:
        if "llm" not in models:
            models["llm"] = _optional(llm_factory)
        return models["llm"]  # type: ignore[return-value]

    def embedder() -> Embedder | None:
        if "embedder" not in models:
            models["embedder"] = _optional(embedder_factory)
        return models["embedder"]  # type: ignore[return-value]

    def get_client(client_id: str) -> ClientConfig:
        if not CLIENT_ID.match(client_id) or not (clients_dir / f"{client_id}.toml").exists():
            raise HTTPException(status_code=404, detail="cliente sconosciuto")
        return load_client(client_id, clients_dir)

    def open_store(client: ClientConfig) -> KnowledgeStore:
        return KnowledgeStore.for_client(client, data_root / client.id)

    @app.get("/health")
    def health() -> dict:
        return {"stato": "ok"}

    @app.get("/v1/{client_id}/status")
    def status(client_id: str) -> dict:
        client = get_client(client_id)
        return {"attivo": agent_status(client.id, data_root)["attivo"]}

    @app.get("/v1/{client_id}/contents/{content_id}")
    def content(client_id: str, content_id: str) -> dict:
        client = get_client(client_id)
        with open_store(client) as store:
            found = approved_content(store, content_id)
        if found is None:
            raise HTTPException(status_code=404, detail="contenuto non disponibile")
        return found

    @app.post("/v1/{client_id}/plan")
    def plan(client_id: str, body: PlanBody, request: Request) -> dict:
        client = get_client(client_id)
        session, created = sessions.get_or_create(client.id, body.session_id)
        signals = session.signals
        if created:
            signals.lingua = body.lingua
            signals.dispositivo = body.dispositivo
            signals.pagina_ingresso = body.pagina
            signals.referrer = body.referrer
        if not signals.pagine_viste or signals.pagine_viste[-1] != body.pagina:
            signals.pagine_viste.append(body.pagina)
        if body.domanda:
            signals.messaggi.append(body.domanda)

        result: dict = {"session_id": session.id, "standard": True, "motivi": [], "piano": None}
        if is_bot(request.headers.get("user-agent", "")):
            result["motivi"] = ["visitatore automatico: pagina standard per i motori di ricerca"]
            return result

        active = agent_status(client.id, data_root)["attivo"]
        with open_store(client) as store:
            estimate = estimate_profile(client, signals, store)
            result["profilo"] = {"id": estimate.profilo, "confidenza": estimate.confidenza}
            planner = Planner(
                client, store, llm() if active else None,
                embedder() if body.domanda else None, active=active,
            )
            response = planner.plan(PlanRequest(
                profilo=estimate.profilo,
                confidenza_profilo=estimate.confidenza,
                lingua=signals.lingua or body.lingua,
                pagina_ingresso=body.pagina,
                domanda=body.domanda,
            ))
            result.update(
                standard=response.standard,
                motivi=response.motivi,
                da_cache=response.da_cache,
                piano=resolve_plan(response.piano, store) if response.piano else None,
            )
        return result

    app.state.sessions = sessions
    return app


def main() -> None:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Avvia l'API di Quuipu.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("quuipu.api.app:create_app", factory=True, host=args.host, port=args.port)

