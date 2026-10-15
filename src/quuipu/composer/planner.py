"""Agente che compone il page plan (specifica §3 e §7).

Flusso: controlli preliminari (agente attivo, profilo abbastanza sicuro),
cache, scelta dei contenuti candidati dalla base di conoscenza, proposta del
piano da parte del modello, validazione, registrazione. In ogni caso di dubbio
la risposta è la pagina standard.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field

from quuipu.composer.components import CTA, MAX_BLOCKS, PAGE_TYPES, describe_library
from quuipu.composer.history import PlanHistory
from quuipu.composer.validator import MAX_BRIDGE_CHARS, validate_plan
from quuipu.config import ClientConfig, load_client
from quuipu.ingestion.llm import LLMClient, LLMError, text_client
from quuipu.knowledge.embeddings import Embedder, default_embedder
from quuipu.knowledge.search import search
from quuipu.knowledge.store import APPROVED, KnowledgeStore

MIN_PROFILE_CONFIDENCE = 0.5
MAX_CANDIDATES_PER_TYPE = 12
MAX_EXCERPT_CHARS = 200
CANDIDATE_TYPES = ("prodotto", "certificazione", "case_study", "faq")

SYSTEM_PROMPT = (
    "Componi la pagina del sito di un'azienda per un visitatore, scegliendo e ordinando "
    "blocchi da una libreria chiusa e contenuti già approvati, citati solo per ID. "
    "Non inventare ID, componenti o informazioni. Rispondi solo con un oggetto JSON."
)

USER_PROMPT = """Azienda: {company} (settore: {sector}).
Visitatore: profilo "{profile_id}" ({profile_name}). Cerca: {looks_for}. Gli interessa: {highlight}.
Lingua della pagina: {language}.
{context}
Componenti disponibili:
{library}

Contenuti approvati disponibili (id | tipo | titolo | estratto):
{candidates}

Regole:
- usa solo componenti e ID elencati sopra, senza ripetere lo stesso contenuto;
- al massimo {max_blocks} blocchi, in ordine di importanza per questo visitatore;
- chiudi con un blocco "{cta}" con la variante più adatta al profilo;
- per ogni blocco puoi scrivere un "raccordo": una frase breve (massimo {max_bridge} caratteri)
  in {language} che introduce il blocco, nel tono dell'azienda, senza promesse, confronti,
  superlativi, prezzi o numeri che non compaiano nei contenuti;
- "confidenza" indica quanto la pagina è adatta al visitatore (da 0 a 1).

Formato della risposta:
{{"profilo": "{profile_id}", "lingua": "{language}", "confidenza": 0.8, "blocchi": [
  {{"componente": "hero", "contenuto_id": "...", "immagine_id": "...", "raccordo": "..."}},
  {{"componente": "griglia_prodotti", "contenuto_id": ["...", "..."], "raccordo": "..."}},
  {{"componente": "{cta}", "variante": "contatto", "raccordo": "..."}}
]}}"""


@dataclass
class PlanRequest:
    profilo: str | None
    confidenza_profilo: float
    lingua: str
    pagina_ingresso: str | None = None
    domanda: str | None = None


@dataclass
class PlanResponse:
    standard: bool
    piano: dict | None = None
    motivi: list[str] = field(default_factory=list)
    scartati: list[dict] = field(default_factory=list)
    avvisi: list[str] = field(default_factory=list)
    da_cache: bool = False
    registro_id: int | None = None


def page_language(client: ClientConfig, requested: str) -> str:
    """Lingua della pagina: quella del visitatore se il cliente la gestisce, altrimenti
    l'inglese se disponibile, altrimenti la lingua principale del cliente."""
    code = (requested or "").split("-")[0].lower()
    if code in client.languages:
        return code
    return "en" if "en" in client.languages else client.languages[0]


class Planner:
    def __init__(
        self,
        client: ClientConfig,
        store: KnowledgeStore,
        llm: LLMClient | None,
        embedder: Embedder | None = None,
        active: bool = True,
        min_profile_confidence: float = MIN_PROFILE_CONFIDENCE,
    ) -> None:
        self.client = client
        self.store = store
        self.llm = llm
        self.embedder = embedder
        self.active = active
        self.min_profile_confidence = min_profile_confidence
        self.history = PlanHistory(store)
        self.profiles = {p.id: p for p in client.profiles}

    def plan(self, request: PlanRequest) -> PlanResponse:
        response = self._plan(request)
        response.registro_id = self.history.log(
            asdict(request), response.standard, response.piano,
            response.motivi, response.scartati, response.da_cache,
        )
        return response

    def _plan(self, request: PlanRequest) -> PlanResponse:
        # Interruttore del cliente / abbonamento non attivo (§10).
        if not self.active:
            return PlanResponse(standard=True, motivi=["agente disattivato"])
        # Segnali deboli: nessuna informazione affidabile sulle preferenze (§6, §10).
        if request.profilo not in self.profiles:
            return PlanResponse(standard=True, motivi=["profilo del visitatore non determinato"])
        if request.confidenza_profilo < self.min_profile_confidence:
            return PlanResponse(
                standard=True,
                motivi=[f"profilo poco sicuro ({request.confidenza_profilo:.2f})"],
            )

        language = page_language(self.client, request.lingua)
        cache_key = None
        version = self.history.knowledge_version()
        if not request.domanda:
            cache_key = f"{request.profilo}|{language}|{request.pagina_ingresso or ''}"
            cached = self.history.cached(cache_key, version)
            if cached:
                return PlanResponse(standard=False, piano=cached, da_cache=True)

        candidates = self.candidates(request, language)
        if not any(c["tipo"] in CANDIDATE_TYPES or c["fonte"] == "pagina" for c in candidates):
            return PlanResponse(standard=True, motivi=["nessun contenuto approvato per questo profilo"])
        if self.llm is None:
            return PlanResponse(standard=True, motivi=["modello linguistico non configurato"])

        try:
            raw = self.llm.complete_json(SYSTEM_PROMPT, self.prompt(request, language, candidates))
        except LLMError as exc:
            return PlanResponse(standard=True, motivi=[f"agente non disponibile: {exc}"])

        # Profilo e lingua li decide il sistema, non il modello.
        if isinstance(raw, dict):
            raw["profilo"] = request.profilo
            raw["lingua"] = language
        result = validate_plan(raw, self.client, self.store)
        if not result.valid:
            return PlanResponse(
                standard=True, motivi=result.errors, scartati=result.discarded, avvisi=result.warnings
            )
        if cache_key:
            self.history.save_cache(cache_key, version, result.plan)
        return PlanResponse(
            standard=False, piano=result.plan, scartati=result.discarded, avvisi=result.warnings
        )

    def candidates(self, request: PlanRequest, language: str) -> list[dict]:
        """Contenuti approvati utili al profilo, con in testa quelli più pertinenti."""
        profile = request.profilo
        ordered: dict[str, dict] = {}

        def add(content: dict) -> None:
            if content["fonte"] == "pagina" and content["lingua"] and content["lingua"] != language:
                return
            ordered.setdefault(content["id"], content)

        approved = self.store.list(stato=APPROVED)
        if request.pagina_ingresso:
            for content in approved:
                if content["fonte"] == "pagina" and content["url"].rstrip("/") == request.pagina_ingresso.rstrip("/"):
                    add(content)
        if request.domanda and self.embedder:
            for hit in search(self.store, self.embedder, request.domanda, k=8, lingua=language):
                add(hit["contenuto"])

        for content_type in CANDIDATE_TYPES:
            matches = [c for c in approved if c["tipo"] == content_type and profile in c["profili"]]
            for content in matches[:MAX_CANDIDATES_PER_TYPE]:
                add(content)
        pages = [c for c in approved if c["fonte"] == "pagina" and c["tipo"] in PAGE_TYPES
                 and profile in c["profili"]]
        for content in pages[:MAX_CANDIDATES_PER_TYPE]:
            add(content)
        images = [c for c in approved if c["fonte"] == "immagine" and profile in c["profili"]]
        for content in images[:MAX_CANDIDATES_PER_TYPE]:
            add(content)
        return list(ordered.values())

    def prompt(self, request: PlanRequest, language: str, candidates: list[dict]) -> str:
        profile = self.profiles[request.profilo]
        context = []
        if request.pagina_ingresso:
            context.append(f"Pagina d'ingresso: {request.pagina_ingresso}")
        if request.domanda:
            context.append(f"Domanda del visitatore: {request.domanda}")
        lines = []
        for c in candidates:
            kind = "immagine" if c["fonte"] == "immagine" else c["tipo"]
            excerpt = c["testo"].replace("\n", " ")[:MAX_EXCERPT_CHARS]
            lines.append(f"{c['id']} | {kind} | {c['titolo']} | {excerpt}")
        return USER_PROMPT.format(
            company=self.client.name, sector=self.client.sector,
            profile_id=profile.id, profile_name=profile.name,
            looks_for=profile.looks_for, highlight=profile.highlight,
            language=language, context="\n".join(context) + ("\n" if context else ""),
            library=describe_library(), candidates="\n".join(lines),
            max_blocks=MAX_BLOCKS, cta=CTA, max_bridge=MAX_BRIDGE_CHARS,
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Compone un page plan di prova per un cliente.")
    parser.add_argument("client", help="ID del cliente")
    parser.add_argument("--profilo", required=True)
    parser.add_argument("--confidenza", type=float, default=0.9, help="confidenza del profilo")
    parser.add_argument("--lingua", default="it")
    parser.add_argument("--pagina", help="URL della pagina d'ingresso")
    parser.add_argument("--domanda", help="domanda del visitatore in chat")
    args = parser.parse_args(argv)

    client = load_client(args.client)
    with KnowledgeStore.for_client(client) as store:
        embedder = None
        try:
            embedder = default_embedder() if args.domanda else None
        except LLMError:
            pass
        planner = Planner(client, store, text_client(), embedder)
        response = planner.plan(PlanRequest(
            args.profilo, args.confidenza, args.lingua, args.pagina, args.domanda,
        ))
    print(json.dumps(asdict(response), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
