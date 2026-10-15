"""Validatore del page plan: l'unico punto da cui passa ciò che arriva al visitatore.

Specifica §7 e §10. Regole:
- il piano deve rispettare lo schema, con profilo e lingua del cliente;
- ogni blocco usa un componente della libreria e solo ID di contenuti
  approvati, del tipo giusto; un blocco non valido viene scartato;
- i testi di raccordo sono brevi, senza promesse né confronti, e non possono
  contenere numeri che non compaiono nei contenuti citati; se non vanno bene
  vengono tolti, il blocco resta;
- se il piano nel suo insieme non è valido (o resta senza contenuti o senza
  invito all'azione), si mostra la pagina standard.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from quuipu.composer.components import COMPONENTS, CTA, MAX_BLOCKS
from quuipu.config import ClientConfig
from quuipu.ingestion.review import NUMBER
from quuipu.knowledge.store import APPROVED, KnowledgeStore

MIN_PLAN_CONFIDENCE = 0.5
MAX_BRIDGE_CHARS = 220
# Espressioni vietate nei testi di raccordo: promesse, superlativi, confronti, offerte.
FORBIDDEN_PHRASES = (
    "garanti", "promett", "il migliore", "i migliori", "la migliore", "le migliori",
    "numero uno", "n. 1", "n.1", "concorren", "sconto", "gratis", "gratuit", "offerta",
    "guarantee", "promise", "the best", "number one", "competitor", "discount", "free",
)


@dataclass
class ValidationResult:
    valid: bool
    plan: dict | None = None
    errors: list[str] = field(default_factory=list)  # motivi della pagina standard
    discarded: list[dict] = field(default_factory=list)  # blocchi scartati
    warnings: list[str] = field(default_factory=list)  # raccordi tolti


def _numbers(text: str) -> set[str]:
    return {n.replace(",", ".") for n in NUMBER.findall(text)}


def check_bridge(text: str, sources: list[dict]) -> list[str]:
    """Motivi per cui un testo di raccordo non è accettabile (vuoto se va bene)."""
    reasons = []
    if len(text) > MAX_BRIDGE_CHARS:
        reasons.append(f"raccordo troppo lungo ({len(text)} caratteri)")
    lowered = text.lower()
    for phrase in FORBIDDEN_PHRASES:
        if re.search(r"\b" + re.escape(phrase), lowered):
            reasons.append(f"raccordo con espressione non ammessa: '{phrase}'")
    source_text = " ".join(
        f"{s['titolo']} {s['testo']} {json.dumps(s['dati'], ensure_ascii=False)}" for s in sources
    )
    missing = _numbers(text) - _numbers(source_text)
    if missing:
        reasons.append(f"raccordo con numeri non presenti nei contenuti: {', '.join(sorted(missing))}")
    return reasons


def _check_content(store: KnowledgeStore, content_id: object, types: tuple[str, ...],
                   language: str) -> tuple[dict | None, str | None]:
    if not isinstance(content_id, str) or not content_id:
        return None, "contenuto_id non valido"
    content = store.get(content_id)
    if content is None:
        return None, f"contenuto '{content_id}' inesistente"
    if content["stato"] != APPROVED:
        return None, f"contenuto '{content_id}' non approvato ({content['stato']})"
    if content["tipo"] not in types or content["fonte"] == "immagine":
        return None, f"contenuto '{content_id}' di tipo '{content['tipo']}' non ammesso"
    if content["fonte"] == "pagina" and content["lingua"] and content["lingua"] != language:
        return None, f"contenuto '{content_id}' in lingua '{content['lingua']}'"
    return content, None


def validate_block(
    raw: object, store: KnowledgeStore, language: str
) -> tuple[dict | None, list[str], list[str]]:
    """(blocco pulito o None, motivi di scarto, avvisi)."""
    if not isinstance(raw, dict):
        return None, ["blocco non è un oggetto"], []
    component = COMPONENTS.get(str(raw.get("componente", "")))
    if component is None:
        return None, [f"componente '{raw.get('componente')}' non presente nella libreria"], []

    block: dict = {"componente": component.name}
    reasons: list[str] = []
    sources: list[dict] = []

    if component.content_types:
        value = raw.get("contenuto_id")
        if component.multiple:
            ids = value if isinstance(value, list) else []
            if not isinstance(value, list):
                reasons.append("contenuto_id deve essere una lista")
            if len(set(map(str, ids))) != len(ids):
                reasons.append("contenuto_id con ID ripetuti")
            if not component.min_items <= len(ids) <= component.max_items:
                reasons.append(
                    f"servono da {component.min_items} a {component.max_items} contenuti, "
                    f"ricevuti {len(ids)}"
                )
        else:
            ids = [value]
        for content_id in ids:
            content, problem = _check_content(store, content_id, component.content_types, language)
            if problem:
                reasons.append(problem)
            else:
                sources.append(content)
        block["contenuto_id"] = list(ids) if component.multiple else value
    elif raw.get("contenuto_id"):
        reasons.append(f"il componente '{component.name}' non accetta contenuti")

    if component.image and raw.get("immagine_id"):
        image = store.get(str(raw["immagine_id"]))
        if image is None or image["fonte"] != "immagine" or image["stato"] != APPROVED:
            reasons.append(f"immagine '{raw['immagine_id']}' non disponibile")
        else:
            block["immagine_id"] = image["id"]
            sources.append(image)

    if component.variants:
        if raw.get("variante") not in component.variants:
            reasons.append(f"variante '{raw.get('variante')}' non prevista")
        else:
            block["variante"] = raw["variante"]

    if reasons:
        return None, reasons, []

    warnings: list[str] = []
    bridge = raw.get("raccordo")
    if isinstance(bridge, str) and bridge.strip():
        problems = check_bridge(bridge.strip(), sources)
        if problems:
            warnings.extend(problems)
        else:
            block["raccordo"] = bridge.strip()
    return block, [], warnings


def validate_plan(
    raw: object,
    client: ClientConfig,
    store: KnowledgeStore,
    min_confidence: float = MIN_PLAN_CONFIDENCE,
) -> ValidationResult:
    result = ValidationResult(valid=False)
    if not isinstance(raw, dict):
        result.errors.append("il piano non è un oggetto JSON")
        return result

    profile = raw.get("profilo")
    if profile not in {p.id for p in client.profiles}:
        result.errors.append(f"profilo '{profile}' non previsto")
    language = raw.get("lingua")
    if language not in client.languages:
        result.errors.append(f"lingua '{language}' non prevista")
    confidence = raw.get("confidenza")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) \
            or not 0 <= confidence <= 1:
        result.errors.append("confidenza mancante o fuori intervallo")
    elif confidence < min_confidence:
        result.errors.append(f"confidenza {confidence:.2f} sotto la soglia {min_confidence:.2f}")
    blocks = raw.get("blocchi")
    if not isinstance(blocks, list) or not blocks:
        result.errors.append("nessun blocco nel piano")
    if result.errors:
        return result

    clean_blocks: list[dict] = []
    used: set[str] = set()
    for index, raw_block in enumerate(blocks):
        if len(clean_blocks) == MAX_BLOCKS:
            result.discarded.append({"indice": index, "motivi": [f"oltre il massimo di {MAX_BLOCKS} blocchi"]})
            continue
        block, reasons, warnings = validate_block(raw_block, store, language)
        if block:
            ids = block.get("contenuto_id")
            ids = set(ids if isinstance(ids, list) else [ids] if ids else [])
            if ids & used:
                block, reasons = None, [f"contenuti già usati: {', '.join(sorted(ids & used))}"]
            else:
                used |= ids
        if block is None:
            name = raw_block.get("componente") if isinstance(raw_block, dict) else None
            result.discarded.append({"indice": index, "componente": name, "motivi": reasons})
            continue
        result.warnings.extend(warnings)
        clean_blocks.append(block)

    if not any(b["componente"] != CTA for b in clean_blocks):
        result.errors.append("nessun blocco di contenuto valido")
    if not any(b["componente"] == CTA for b in clean_blocks):
        result.errors.append("manca l'invito all'azione (cta_contatto)")
    if result.errors:
        return result

    result.valid = True
    result.plan = {
        "profilo": profile,
        "lingua": language,
        "confidenza": float(confidence),
        "blocchi": clean_blocks,
    }
    return result
