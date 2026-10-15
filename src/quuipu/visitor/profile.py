"""Stima del profilo del visitatore dai segnali della sessione (specifica §6).

Il profilo è una probabilità su un elenco chiuso, non un giudizio sulla
persona, e vive solo nella sessione. Ogni segnale aggiunge punti ai profili
che indica; la probabilità di un profilo è (1 + punti) / somma, quindi senza
segnali tutti i profili sono equiprobabili e la confidenza resta bassa.

Pesi dei segnali, dal più forte:
- dichiarazione in chat ("siamo un distributore tedesco"): prevale sugli altri;
- query di ricerca trasmessa dal referrer;
- provenienza (dominio del referrer);
- pagina d'ingresso e pagine viste, tramite i profili assegnati alle pagine
  in fase di classificazione;
- lingua del browser diversa da quella principale del sito.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

from quuipu.config import ClientConfig, VisitorProfile
from quuipu.knowledge.store import APPROVED, KnowledgeStore

WEIGHT_MESSAGE = 6.0
WEIGHT_QUERY = 3.0
WEIGHT_REFERRER = 1.5
WEIGHT_ENTRY_PAGE = 2.0
WEIGHT_VIEWED_PAGE = 1.0
WEIGHT_FOREIGN_LANGUAGE = 1.0
MAX_VIEWED_PAGES = 10
QUERY_PARAMS = ("q", "p", "query", "text", "wd", "search")


@dataclass
class Signals:
    lingua: str = ""
    dispositivo: str = ""
    pagina_ingresso: str = ""
    referrer: str = ""
    pagine_viste: list[str] = field(default_factory=list)
    messaggi: list[str] = field(default_factory=list)


@dataclass
class ProfileEstimate:
    profilo: str | None
    confidenza: float
    probabilita: dict[str, float]
    segnali: list[str]


def normalize(text: str) -> str:
    """Minuscolo e senza accenti, per confrontare parole chiave."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def matches(text: str, keywords: tuple[str, ...]) -> list[str]:
    """Parole chiave trovate nel testo, come inizio di parola."""
    norm = normalize(text)
    return [kw for kw in keywords if re.search(r"(?<!\w)" + re.escape(normalize(kw)), norm)]


def search_query(referrer: str) -> str:
    """Query di ricerca contenuta nel referrer, se il motore la trasmette."""
    params = parse_qs(urlsplit(referrer).query)
    for name in QUERY_PARAMS:
        if params.get(name):
            return params[name][0]
    return ""


def _host(url: str) -> str:
    return urlsplit(url).netloc.lower()


def estimate_profile(
    client: ClientConfig, signals: Signals, store: KnowledgeStore | None = None
) -> ProfileEstimate:
    profiles: dict[str, VisitorProfile] = {p.id: p for p in client.profiles}
    scores = {pid: 0.0 for pid in profiles}
    explanations: list[str] = []

    def add(profile_ids, weight: float, why: str) -> None:
        profile_ids = [p for p in profile_ids if p in scores]
        for pid in profile_ids:
            scores[pid] += weight
        if profile_ids:
            explanations.append(f"{why}: {', '.join(profile_ids)}")

    # Dichiarazioni in chat: il segnale più forte.
    for message in signals.messaggi:
        for pid, profile in profiles.items():
            if matches(message, profile.keywords):
                add([pid], WEIGHT_MESSAGE, "dichiarazione in chat")

    # Provenienza esterna e query di ricerca.
    referrer_host = _host(signals.referrer)
    if referrer_host and referrer_host != _host(client.base_url):
        query = search_query(signals.referrer)
        if query:
            for pid, profile in profiles.items():
                if matches(query, profile.keywords):
                    add([pid], WEIGHT_QUERY, "query di ricerca")
        for pid, profile in profiles.items():
            if any(part in referrer_host for part in profile.referrers):
                add([pid], WEIGHT_REFERRER, f"provenienza da {referrer_host}")

    # Pagine: d'ingresso e viste durante la sessione, tramite la classificazione.
    if store is not None:
        pages = [(signals.pagina_ingresso, WEIGHT_ENTRY_PAGE, "pagina d'ingresso")] if signals.pagina_ingresso else []
        pages += [(url, WEIGHT_VIEWED_PAGE, "pagina vista")
                  for url in signals.pagine_viste[-MAX_VIEWED_PAGES:]]
        for url, weight, why in pages:
            page = store.find_page(url)
            if page and page["stato"] == APPROVED and page["profili"]:
                # Una pagina utile a tutti i profili non distingue nessuno.
                add(page["profili"], weight / len(page["profili"]), why)

    # Lingua del browser diversa da quella principale del sito.
    language = (signals.lingua or "").split("-")[0].lower()
    if language and client.languages and language != client.languages[0]:
        add([pid for pid, p in profiles.items() if p.foreign], WEIGHT_FOREIGN_LANGUAGE,
            f"browser in lingua '{language}'")

    total = sum(1.0 + s for s in scores.values())
    probabilities = {pid: round((1.0 + s) / total, 4) for pid, s in scores.items()}
    ranked = sorted(probabilities, key=probabilities.get, reverse=True)
    best = ranked[0] if ranked else None
    # Nessun segnale, o parità in testa: i segnali non distinguono nessun profilo.
    if best is not None and (
        scores[best] == 0
        or (len(ranked) > 1 and probabilities[ranked[1]] == probabilities[best])
    ):
        best = None
    return ProfileEstimate(
        profilo=best,
        confidenza=probabilities.get(best, 0.0) if best else 0.0,
        probabilita=probabilities,
        segnali=explanations,
    )
