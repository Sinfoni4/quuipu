"""Pipeline completa di ingestione di un cliente (specifica §4 e §5).

Esegue in ordine: crawl del sito, download di PDF e immagini, parsing dei
PDF, analisi delle immagini, classificazione, aggiornamento della base di
conoscenza e indicizzazione semantica. La cartella dedicata del cliente, se
indicata, si aggiunge ai file scaricati dal sito.

Se il modello per le immagini o per gli embedding non è configurato, il
passaggio relativo viene saltato con un avviso e il resto prosegue.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable

import httpx

from quuipu.config import ClientConfig, data_dir, load_client
from quuipu.ingestion.assets import download_assets
from quuipu.ingestion.classification import classify_contents
from quuipu.ingestion.crawler import Crawler, save_result
from quuipu.ingestion.documents import parse_documents
from quuipu.ingestion.images import describe_images
from quuipu.ingestion.llm import LLMClient, LLMError, text_client, vision_client
from quuipu.knowledge.build import build_contents
from quuipu.knowledge.embeddings import Embedder, default_embedder
from quuipu.knowledge.search import index_contents
from quuipu.knowledge.store import KnowledgeStore


def run_ingestion(
    client: ClientConfig,
    *,
    base_dir: Path | None = None,
    folder: Path | None = None,
    skip_crawl: bool = False,
    http: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
    text_llm: LLMClient | None = None,
    vision_llm: LLMClient | None = None,
    embedder: Embedder | None = None,
    log: Callable[[str], None] = print,
) -> dict:
    base = base_dir or data_dir() / client.id
    summary: dict = {"client": client.id, "avvisi": []}

    def warn(message: str) -> None:
        summary["avvisi"].append(message)
        log(f"ATTENZIONE: {message}")

    # 1. Crawl del sito
    manifest_path = base / "crawl" / "manifest.json"
    if skip_crawl:
        if not manifest_path.exists():
            raise FileNotFoundError("nessun crawl precedente: eseguire senza --skip-crawl")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        log("1/7 Crawl saltato, uso il risultato precedente")
    else:
        log("1/7 Crawl del sito")
        result = Crawler(client, http=http, sleep=sleep).run()
        manifest = save_result(client, result, base / "crawl")
    summary["pagine"] = len(manifest["pages"])
    summary["modifiche_sito"] = {k: len(v) for k, v in manifest["changes"].items()}

    # 2. Download di PDF e immagini
    log("2/7 Download di PDF e immagini")
    assets = download_assets(client, manifest, base / "assets", http=http, sleep=sleep)
    summary["file_scaricati"] = {"documenti": len(assets["documents"]), "immagini": len(assets["images"])}
    folders = [base / "assets" / "documents"] + ([folder] if folder else [])
    image_folders = [base / "assets" / "images"] + ([folder] if folder else [])

    # 3. Parsing dei PDF
    log("3/7 Parsing dei PDF")
    text_llm = text_llm or text_client()
    products = parse_documents(client, folders, text_llm, base / "knowledge")
    summary["prodotti"] = len(products["prodotti"])

    # 4. Analisi delle immagini
    log("4/7 Analisi delle immagini")
    try:
        vision_llm = vision_llm or vision_client()
    except LLMError as exc:
        vision_llm = None
        warn(f"immagini non analizzate: {exc}")
    if vision_llm:
        images = describe_images(client, image_folders, vision_llm, base / "knowledge")
        summary["immagini"] = len(images["immagini"])

    # 5. Classificazione per tipo e profilo
    log("5/7 Classificazione dei contenuti")
    classification = classify_contents(client, text_llm, base)
    summary["per_profilo"] = classification["per_profilo"]

    # 6. Base di conoscenza
    log("6/7 Aggiornamento della base di conoscenza")
    language = client.languages[0] if client.languages else ""
    with KnowledgeStore.for_client(client, base) as store:
        changes = store.sync(build_contents(base, language))
        summary["base_di_conoscenza"] = {k: len(v) for k, v in changes.items()}

        # 7. Indice semantico
        log("7/7 Indicizzazione semantica")
        try:
            embedder = embedder or default_embedder()
        except LLMError as exc:
            embedder = None
            warn(f"indice semantico non aggiornato: {exc}")
        if embedder:
            summary["indicizzati"] = index_contents(store, embedder)
        summary["stati"] = store.counts()

    (base / "ingestion-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ingestione completa dei contenuti di un cliente.")
    parser.add_argument("client", help="ID del cliente (file in clients/)")
    parser.add_argument("--folder", type=Path, help="cartella dedicata del cliente")
    parser.add_argument("--skip-crawl", action="store_true", help="riusa l'ultimo crawl")
    parser.add_argument("--max-pages", type=int, help="limite di pagine per il crawl")
    args = parser.parse_args(argv)

    client = load_client(args.client)
    if args.max_pages:
        client = replace(client, crawl=replace(client.crawl, max_pages=args.max_pages))
    summary = run_ingestion(client, folder=args.folder, skip_crawl=args.skip_crawl)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
