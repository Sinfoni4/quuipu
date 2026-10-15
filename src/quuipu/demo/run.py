"""Demo simulata completa di Quuipu.

1. Genera il sito della cantina inventata e lo serve su http://127.0.0.1:8765.
2. Esegue la pipeline vera (crawl, PDF, immagini, classificazione, base di
   conoscenza, indice) con il modello simulato al posto di Mistral.
3. Simula il cliente che approva le schede da confermare, tranne quelle con
   dati sospetti, che restano in coda di revisione.
4. Avvia l'API in modalità debug con la pagina di demo su
   http://127.0.0.1:8000/demo/.

Tutto avviene in data/demo/, che viene ricreata a ogni avvio.
"""

from __future__ import annotations

import argparse
import functools
import shutil
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from quuipu.api.app import create_app
from quuipu.composer.history import PlanHistory
from quuipu.config import data_dir, load_client
from quuipu.control import agent_status, set_agent_active
from quuipu.demo.simulated import SimulatedEmbedder, SimulatedMistral
from quuipu.demo.site import PAGES, build_site
from quuipu.knowledge.store import TO_REVIEW, KnowledgeStore
from quuipu.pipeline import run_ingestion

CLIENT_ID = "valmora"
SITE_PORT = 8765
API_PORT = 8000
STATIC_DIR = Path(__file__).parent / "static"
# Motivi che il cliente simulato accetta confermando la scheda.
ROUTINE_REASONS = ("prezzo da confermare", "specifiche tecniche da confermare", "certificazioni da confermare")

SCENARIOS = [
    {"t": "Visitatore qualunque", "d": "Arriva sulla home, senza altri segnali.",
     "pagina": "/", "lingua": "it-IT"},
    {"t": "Appassionata da Instagram", "d": "Clicca un post e atterra sulle degustazioni.",
     "pagina": "/degustazioni/", "referrer": "https://www.instagram.com/", "lingua": "it-IT"},
    {"t": "Buyer da ricerca Bing",
     "d": "Cerca «italian organic wine importers wholesale», browser in inglese.",
     "pagina": "/en/export/", "lingua": "en-GB",
     "referrer": "https://www.bing.com/search?q=italian+organic+wine+importers+wholesale"},
    {"t": "Importatore tedesco in chat",
     "d": "Browser in tedesco, scrive: «We are a wine importer from Germany…»",
     "pagina": "/en/", "lingua": "de-DE",
     "domanda": "We are a wine importer from Germany. Do you have organic certifications?"},
    {"t": "Ristoratore che chiede il listino",
     "d": "Scrive: «Ho un ristorante a Milano: avete un listino?»",
     "pagina": "/vini/", "lingua": "it-IT",
     "domanda": "Ho un ristorante a Milano: avete un listino per la ristorazione?"},
    {"t": "Ente da gara d'appalto", "d": "Cerca una fornitura per una mensa: segnali ancora deboli.",
     "pagina": "/certificazioni/", "lingua": "it-IT",
     "referrer": "https://www.bing.com/search?q=fornitura+vino+biologico+gara+d%27appalto+mensa"},
]

CLIENT_TOML = """id = "valmora"
name = "Cantina Valmora"
sector = "agrifood"
base_url = "{site}/"
languages = ["it", "en"]

[ingestion]
confidence_threshold = 0.7
image_categories = ["bottiglia", "vigneto", "cantina", "degustazione", "struttura", "altro"]

[crawl]
max_pages = 100
delay_seconds = 0
exclude = ["/area-riservata/"]
"""


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:  # niente log per ogni file servito
        pass


def serve_site(root: Path, port: int) -> ThreadingHTTPServer:
    handler = functools.partial(_QuietHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def prepare(base: Path, site_port: int = SITE_PORT, log=print) -> dict:
    """Ricrea sito e dati della demo ed esegue l'ingestione simulata.

    site_port=0 sceglie una porta libera (usato nei test)."""
    if base.exists():
        shutil.rmtree(base)
    (base / "site").mkdir(parents=True)
    server = serve_site(base / "site", site_port)
    site_url = f"http://127.0.0.1:{server.server_address[1]}"
    build_site(base / "site", site_url)
    clients = base / "clients"
    clients.mkdir(parents=True)
    (clients / f"{CLIENT_ID}.toml").write_text(CLIENT_TOML.format(site=site_url), encoding="utf-8")

    client = load_client(CLIENT_ID, clients)
    summary = run_ingestion(
        client, base_dir=base / "data" / CLIENT_ID, text_llm=SimulatedMistral(),
        vision_llm=SimulatedMistral(), embedder=SimulatedEmbedder(), sleep=lambda _: None, log=log,
    )

    approved = []
    with KnowledgeStore.for_client(client, base / "data" / CLIENT_ID) as store:
        for content in store.list(stato=TO_REVIEW):
            if content["motivi"] and all(r in ROUTINE_REASONS for r in content["motivi"]):
                store.decide(content["id"], "approvato")
                approved.append(content["titolo"] or content["id"])
        summary["approvati_dal_cliente"] = approved
        summary["stati"] = store.counts()
    summary["sito"] = site_url
    return summary


class AgentSwitch(BaseModel):
    attivo: bool


def create_demo_app(base: Path, summary: dict) -> FastAPI:
    data_root = base / "data"
    clients = base / "clients"
    app = create_app(
        clients_dir=clients, data_root=data_root, llm_factory=SimulatedMistral,
        embedder_factory=SimulatedEmbedder, debug=True,
    )
    client = load_client(CLIENT_ID, clients)

    @app.get("/")
    def root() -> RedirectResponse:
        return RedirectResponse("/demo/")

    @app.get("/demo-api/info")
    def info() -> dict:
        with KnowledgeStore.for_client(client, data_root / CLIENT_ID) as store:
            review = [
                {"id": c["id"], "fonte": c["fonte"], "titolo": c["titolo"] or c["testo"][:60],
                 "motivi": c["motivi"]}
                for c in store.list(stato=TO_REVIEW)
            ]
            contents = [
                {"id": c["id"], "fonte": c["fonte"], "tipo": c["tipo"], "lingua": c["lingua"],
                 "titolo": c["titolo"] or c["testo"][:60], "profili": c["profili"], "stato": c["stato"]}
                for c in store.list()
            ]
            log = PlanHistory(store).recent(10)
            counts = store.counts()
        return {
            "sintesi": summary, "stati": counts, "in_revisione": review, "contenuti": contents,
            "pagine": [{"percorso": p, "lingua": v[0], "titolo": v[1].split(" – ")[0]} for p, v in PAGES.items()],
            "registro": log, "agente": agent_status(CLIENT_ID, data_root), "scenari": SCENARIOS,
        }

    @app.post("/demo-api/agent")
    def switch(body: AgentSwitch) -> dict:
        return set_agent_active(CLIENT_ID, body.attivo, "demo", base=data_root)

    app.mount("/demo", StaticFiles(directory=STATIC_DIR, html=True), name="demo")
    return app


def main(argv: list[str] | None = None) -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Avvia la demo simulata di Quuipu.")
    parser.add_argument("--port", type=int, default=API_PORT)
    parser.add_argument("--site-port", type=int, default=SITE_PORT)
    args = parser.parse_args(argv)

    base = data_dir() / "demo"
    print("Preparo la demo: sito inventato, ingestione con modello simulato...")
    summary = prepare(base, args.site_port)
    print(f"Fatto. Stati dei contenuti: {summary['stati']}")
    print(f"Sito della cantina: {summary['sito']}")
    print(f"Pagina di demo:     http://127.0.0.1:{args.port}/demo/")
    uvicorn.run(create_demo_app(base, summary), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
