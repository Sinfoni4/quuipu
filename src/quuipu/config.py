"""Configurazione dei clienti, letta dai file TOML in clients/."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

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
    # Segnali per riconoscere il profilo (specifica §6). Le parole chiave valgono
    # come inizio di parola: "import" riconosce anche "importatore" e "importer".
    keywords: tuple[str, ...] = ()
    referrers: tuple[str, ...] = ()  # pezzi di dominio di provenienza, es. "linkedin."
    foreign: bool = False  # un browser in lingua estera è un indizio per questo profilo


# Profili generici della specifica (§2). Ogni cliente può sostituirli con
# profili specifici del proprio settore nella sezione [[profiles]] del TOML.
DEFAULT_PROFILES = (
    VisitorProfile(
        "buyer_estero", "Buyer estero (B2B)", "Affidabilità, volumi, export",
        "Certificazioni, capacità produttiva, contatti commerciali, lingua",
        keywords=("import", "export", "esport", "wholesale", "ingrosso", "buyer", "b2b",
                  "volum", "container", "pallet", "bancal", "international", "internazional",
                  "einkauf", "importateur", "importador"),
        referrers=("linkedin.", "alibaba.", "europages.", "kompass."),
        foreign=True,
    ),
    VisitorProfile(
        "distributore", "Distributore o rivenditore", "Margini, condizioni, cataloghi",
        "Listino su richiesta, cataloghi PDF, condizioni di fornitura",
        keywords=("distribut", "rivendit", "reseller", "retailer", "enotec", "wine shop",
                  "horeca", "ristorant", "restaurant", "listino", "price list", "catalog",
                  "condizioni di fornitura", "agente", "agent", "händler", "grossist"),
        referrers=("linkedin.",),
    ),
    VisitorProfile(
        "privato", "Cliente privato", "Prodotto e fiducia",
        "Storia dell'azienda, schede prodotto, dove acquistare",
        keywords=("acquist", "comprare", "compro", "buy", "shop", "negozio", "regal", "gift",
                  "degustazion", "tasting", "visit", "abbinament", "pairing", "bottigli",
                  "bottle", "cena", "dinner", "prezzo", "price"),
        referrers=("instagram.", "facebook.", "tripadvisor.", "vivino."),
    ),
    VisitorProfile(
        "ente", "Ente o stazione appaltante", "Conformità e requisiti",
        "Certificazioni, documentazione, referenze",
        keywords=("bando", "bandi", "gara d", "gare d", "appalt", "tender", "conformit", "compliance",
                  "pubblica amministrazione", "comune di", "regione", "ministero",
                  "public authority", "procurement"),
        referrers=(".gov.", ".gov", "acquistinretepa.", "anticorruzione."),
    ),
    VisitorProfile(
        "curioso", "Candidato o curioso", "Chi siete",
        "Chi siamo, lavora con noi, notizie",
        keywords=("lavora con noi", "lavoro", "career", "job", "stage", "tirocin",
                  "internship", "curriculum", "storia", "history", "chi siamo", "about us",
                  "news", "notizi"),
        referrers=("indeed.", "infojobs.", "glassdoor."),
    ),
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
    # Siti da cui il widget può chiamare l'API (CORS).
    allowed_origins: tuple[str, ...] = ()


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
            VisitorProfile(
                p["id"], p["name"], p["looks_for"], p["highlight"],
                keywords=tuple(p.get("keywords", ())),
                referrers=tuple(p.get("referrers", ())),
                foreign=p.get("foreign", False),
            )
            for p in raw["profiles"]
        ) if raw.get("profiles") else DEFAULT_PROFILES,
        allowed_origins=tuple(raw.get("allowed_origins", ())) or (_origin(raw["base_url"]),),
    )


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"
