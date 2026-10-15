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


@dataclass(frozen=True)
class ClientConfig:
    id: str
    name: str
    sector: str
    base_url: str
    languages: tuple[str, ...]
    crawl: CrawlSettings = field(default_factory=CrawlSettings)


def load_client(client_id: str, clients_dir: Path | None = None) -> ClientConfig:
    path = (clients_dir or CLIENTS_DIR) / f"{client_id}.toml"
    with path.open("rb") as f:
        raw = tomllib.load(f)
    crawl = raw.get("crawl", {})
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
    )
