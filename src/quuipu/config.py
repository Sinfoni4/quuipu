"""Configurazione dei clienti, letta dai file TOML in clients/."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
CLIENTS_DIR = ROOT_DIR / "clients"


def data_dir() -> Path:
    """Cartella dei dati scaricati e generati (esclusa da git)."""
    return Path(os.environ.get("QUUIPU_DATA_DIR", ROOT_DIR / "data"))


@dataclass(frozen=True)
class CrawlSettings:
    max_pages: int = 300
    delay_seconds: float = 1.0
    timeout_seconds: float = 20.0
    exclude: tuple[str, ...] = ()


DEFAULT_IMAGE_CATEGORIES = ("prodotto", "struttura", "persone", "evento", "paesaggio", "logo", "altro")


@dataclass(frozen=True)
class IngestionSettings:
    # Sotto questa confidenza un elemento estratto va in coda di revisione.
    confidence_threshold: float = 0.7
    image_categories: tuple[str, ...] = DEFAULT_IMAGE_CATEGORIES


@dataclass(frozen=True)
class VisitorProfile:
    id: str
    name: str
    looks_for: str
    highlight: str


# Profili generici della specifica (§2). Ogni cliente può sostituirli con
# profili specifici del proprio settore nella sezione [[profiles]] del TOML.
DEFAULT_PROFILES = (
    VisitorProfile("buyer_estero", "Buyer estero (B2B)", "Affidabilità, volumi, export",
                   "Certificazioni, capacità produttiva, contatti commerciali, lingua"),
    VisitorProfile("distributore", "Distributore o rivenditore", "Margini, condizioni, cataloghi",
                   "Listino su richiesta, cataloghi PDF, condizioni di fornitura"),
    VisitorProfile("privato", "Cliente privato", "Prodotto e fiducia",
                   "Storia dell'azienda, schede prodotto, dove acquistare"),
    VisitorProfile("ente", "Ente o stazione appaltante", "Conformità e requisiti",
                   "Certificazioni, documentazione, referenze"),
    VisitorProfile("curioso", "Candidato o curioso", "Chi siete",
                   "Chi siamo, lavora con noi, notizie"),
)


@dataclass(frozen=True)
class ClientConfig:
    id: str
    name: str
    sector: str
    base_url: str
    languages: tuple[str, ...]
    crawl: CrawlSettings = field(default_factory=CrawlSettings)
    ingestion: IngestionSettings = field(default_factory=IngestionSettings)
    profiles: tuple[VisitorProfile, ...] = DEFAULT_PROFILES


def load_client(client_id: str, clients_dir: Path | None = None) -> ClientConfig:
    path = (clients_dir or CLIENTS_DIR) / f"{client_id}.toml"
    with path.open("rb") as f:
        raw = tomllib.load(f)
    crawl = raw.get("crawl", {})
    ingestion = raw.get("ingestion", {})
    return ClientConfig(
        id=raw["id"],
        name=raw["name"],
        sector=raw["sector"],
        base_url=raw["base_url"],
        languages=tuple(raw["languages"]),
        crawl=CrawlSettings(
            max_pages=crawl.get("max_pages", CrawlSettings.max_pages),
            delay_seconds=crawl.get("delay_seconds", CrawlSettings.delay_seconds),
            timeout_seconds=crawl.get("timeout_seconds", CrawlSettings.timeout_seconds),
            exclude=tuple(crawl.get("exclude", ())),
        ),
        ingestion=IngestionSettings(
            confidence_threshold=ingestion.get(
                "confidence_threshold", IngestionSettings.confidence_threshold
            ),
            image_categories=tuple(
                ingestion.get("image_categories", DEFAULT_IMAGE_CATEGORIES)
            ),
        ),
        profiles=tuple(
            VisitorProfile(p["id"], p["name"], p["looks_for"], p["highlight"])
            for p in raw["profiles"]
        ) if raw.get("profiles") else DEFAULT_PROFILES,
    )
