"""Modello simulato: imita le risposte di Mistral con regole fisse.

Serve solo alla demo e ai test, per vedere la piattaforma al lavoro senza
chiamare un modello vero. Riconosce il tipo di richiesta dal prompt e risponde
nello stesso formato JSON che chiediamo a Mistral.

Commette di proposito alcuni errori tipici di un modello, per mostrare i
controlli della piattaforma:
- aggiunge a un vino una specifica che nel catalogo non c'è;
- per il buyer estero scrive un testo di raccordo con una promessa e un numero inventato;
- per il distributore cita un contenuto che non esiste.
"""

from __future__ import annotations

import hashlib
import re
from typing import Sequence
from urllib.parse import urlsplit

from quuipu.demo.files import png_color
from quuipu.ingestion.llm import ImageInput
from quuipu.visitor.profile import normalize

# Colori delle foto di prova e ciò che il "modello" ci vede.
IMAGE_COLORS = {
    (74, 124, 58): ("Filari di vite in collina sotto un cielo sereno.", ["vigneto", "collina", "vite"], "vigneto", 0.92),
    (110, 20, 40): ("Bottiglia di vino rosso con etichetta Valmora.", ["bottiglia", "vino rosso", "etichetta"], "bottiglia", 0.9),
    (120, 84, 52): ("Botti di rovere allineate nella cantina sotterranea.", ["cantina", "botti", "rovere"], "cantina", 0.88),
    (196, 154, 58): ("Calici di spumante su un tavolo durante una degustazione.", ["degustazione", "calici", "spumante"], "degustazione", 0.9),
}
UNCERTAIN_IMAGE = ("Immagine poco leggibile, forse un dettaglio di un edificio.", ["edificio"], "struttura", 0.4)

# Tipo di pagina riconosciuto dal percorso dell'URL.
PAGE_RULES = (
    (("privacy",), "altro"),
    (("news",), "notizia"),
    (("storia", "story"), "chi_siamo"),
    (("vini", "wines"), "prodotto"),
    (("certificaz", "certific"), "certificazione"),
    (("export",), "chi_siamo"),
    (("referenze", "references"), "case_study"),
    (("degustaz", "tasting"), "contatto"),
    (("faq",), "faq"),
    (("contatti", "contact"), "contatto"),
)
PROFILES_BY_TYPE = {
    "chi_siamo": ["privato", "curioso", "buyer_estero"],
    "prodotto": ["privato", "distributore", "buyer_estero"],
    "certificazione": ["buyer_estero", "ente", "distributore"],
    "case_study": ["distributore", "buyer_estero"],
    "contatto": ["privato", "distributore", "buyer_estero", "ente"],
    "faq": ["privato", "distributore", "buyer_estero", "ente"],
    "notizia": ["curioso", "privato"],
    "altro": [],
}
EXPORT_PROFILES = ["buyer_estero", "distributore"]
TASTING_PROFILES = ["privato"]
PROFILES_BY_IMAGE = {
    "vigneto": ["privato", "curioso", "buyer_estero"],
    "bottiglia": ["privato", "distributore", "buyer_estero"],
    "cantina": ["privato", "curioso", "ente"],
    "degustazione": ["privato"],
}

# Ricetta della pagina per profilo: parola da cercare per l'hero, tipi di
# contenuto in ordine di importanza, variante dell'invito all'azione.
RECIPES = {
    "buyer_estero": (("export",), ("certificazione", "prodotto", "case_study", "faq"), "preventivo"),
    "distributore": (("export",), ("prodotto", "case_study", "certificazione"), "campione"),
    "privato": (("storia", "story"), ("prodotto", "faq"), "degustazione"),
    "ente": (("certific",), ("certificazione", "faq"), "contatto"),
    "curioso": (("storia", "story"), ("faq",), "contatto"),
}
COMPONENT_FOR_TYPE = {
    "certificazione": ("certificazioni", 3),
    "prodotto": ("griglia_prodotti", 6),
    "case_study": ("case_study", 2),
    "faq": ("faq", 3),
}
BRIDGES = {
    "it": {
        "hero": "Benvenuti in Cantina Valmora.",
        "certificazioni": "Qualità documentata, passo dopo passo.",
        "griglia_prodotti": "Una selezione dei nostri vini.",
        "case_study": "Chi lavora già con noi.",
        "faq": "Le risposte alle domande più frequenti.",
        "cta_contatto": "Parliamone insieme.",
    },
    "en": {
        "hero": "Welcome to Cantina Valmora.",
        "certificazioni": "Quality you can verify.",
        "griglia_prodotti": "A selection of our wines.",
        "case_study": "Partners who already work with us.",
        "faq": "Answers to frequent questions.",
        "cta_contatto": "Let's talk.",
    },
}
FAULTY_BRIDGE = {
    "it": "Garantiamo consegne in 48 ore in tutta Europa.",
    "en": "We guarantee delivery in 48 hours across Europe.",
}


class SimulatedMistral:
    """Implementa il protocollo LLMClient senza chiamare nessun servizio."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def complete_json(self, system: str, user: str, images: Sequence[ImageInput] = ()) -> dict:
        self.calls.append(user[:80])
        if images:
            return self._describe_image(images[0])
        if "Componenti disponibili:" in user:
            return self._compose_page(user)
        if "CONTENUTI:" in user:
            return self._classify(user)
        if "TESTO:" in user:
            return self._extract_products(user.split("TESTO:", 1)[1])
        return {}

    # --- immagini ---------------------------------------------------------

    def _describe_image(self, image: ImageInput) -> dict:
        color = png_color(image.data)
        description, tags, category, confidence = IMAGE_COLORS.get(color, UNCERTAIN_IMAGE)
        return {"descrizione": description, "tag": tags, "categoria": category, "confidenza": confidence}

    # --- schede prodotto dai PDF -------------------------------------------

    def _extract_products(self, text: str) -> dict:
        products: list[dict] = []
        current: dict | None = None
        for line in text.splitlines():
            if ":" not in line:
                continue
            key, value = (part.strip() for part in line.split(":", 1))
            if key == "Vino":
                current = {"nome": value, "specifiche": {}, "certificazioni": [], "confidenza": 0.9}
                products.append(current)
            elif current is None:
                continue
            elif key == "Categoria":
                current["categoria"] = value
            elif key == "Descrizione":
                current["descrizione"] = value
            elif key == "Prezzo":
                current["prezzo"] = value
            elif key == "Certificazioni":
                current["certificazioni"] = [c.strip() for c in value.split(",") if c.strip()]
            else:
                current["specifiche"][key] = value
        # Errore voluto: un dato "dedotto" che nel catalogo non c'è.
        for product in products:
            if "Amarone" in product["nome"]:
                product["specifiche"]["Affinamento"] = "36 mesi in botte"
        return {"prodotti": products}

    # --- classificazione ----------------------------------------------------

    def _classify(self, user: str) -> dict:
        items = re.findall(
            r"### id: (\S+) \(fonte: (\w+)[^)]*\)\n(.*?)(?=\n\n### id: |\Z)", user, re.DOTALL
        )
        results = []
        for content_id, source, summary in items:
            if source == "pagina":
                url = re.search(r"URL: (\S+)", summary)
                path = urlsplit(url.group(1)).path.lower() if url else ""
                content_type = next(
                    (t for words, t in PAGE_RULES if any(w in path for w in words)), "chi_siamo"
                )
                profiles = PROFILES_BY_TYPE[content_type]
                if "export" in path:
                    profiles = EXPORT_PROFILES
                elif "degustaz" in path or "tasting" in path:
                    profiles = TASTING_PROFILES
                confidence = 0.6 if content_type == "notizia" else 0.9
                results.append({"id": content_id, "tipo": content_type, "profili": profiles,
                                "confidenza": confidence})
            elif source == "prodotto":
                results.append({"id": content_id, "profili": PROFILES_BY_TYPE["prodotto"],
                                "confidenza": 0.9})
            else:
                category = re.search(r"Categoria: (\w+)", summary)
                profiles = PROFILES_BY_IMAGE.get(category.group(1) if category else "", [])
                results.append({"id": content_id, "profili": profiles or ["privato"],
                                "confidenza": 0.85})
        return {"classificazioni": results}

    # --- page plan ------------------------------------------------------------

    def _compose_page(self, user: str) -> dict:
        profile = re.search(r'profilo "(\w+)"', user).group(1)
        language = re.search(r"Lingua della pagina: (\w+)", user).group(1)
        question = "Domanda del visitatore:" in user
        section = user.split("(id | tipo | titolo | estratto):", 1)[1].split("\nRegole:", 1)[0]
        candidates = []
        for line in section.strip().splitlines():
            parts = [p.strip() for p in line.split(" | ")]
            if len(parts) >= 3:
                candidates.append({"id": parts[0], "tipo": parts[1], "titolo": normalize(parts[2])})

        hero_words, order, cta = RECIPES.get(profile, RECIPES["privato"])
        pages = [c for c in candidates if c["id"].startswith("page-")]
        hero = next((c for c in pages if any(w in c["titolo"] for w in hero_words)), None)
        hero = hero or next((c for c in pages if c["tipo"] == "chi_siamo"), None) or (pages[0] if pages else None)
        images = [c for c in candidates if c["tipo"] == "immagine"]
        bridges = BRIDGES.get(language, BRIDGES["en"])

        blocks: list[dict] = []
        if hero:
            block = {"componente": "hero", "contenuto_id": hero["id"], "raccordo": bridges["hero"]}
            if images:
                block["immagine_id"] = images[0]["id"]
            blocks.append(block)
        if question:  # con una domanda in chat, le FAQ salgono subito dopo l'apertura
            order = ("faq",) + tuple(t for t in order if t != "faq")
        used = {hero["id"]} if hero else set()
        for content_type in order:
            component, limit = COMPONENT_FOR_TYPE[content_type]
            ids = [c["id"] for c in candidates
                   if c["tipo"] == content_type and c["id"] not in used
                   and (content_type != "prodotto" or c["id"].startswith("prod-"))][:limit]
            if not ids:
                continue
            used.update(ids)
            raccordo = bridges[component]
            if profile == "buyer_estero" and component == "griglia_prodotti":
                raccordo = FAULTY_BRIDGE.get(language, FAULTY_BRIDGE["en"])  # errore voluto
            blocks.append({"componente": component, "contenuto_id": ids, "raccordo": raccordo})
        if profile == "distributore":  # errore voluto: un contenuto che non esiste
            blocks.append({"componente": "case_study", "contenuto_id": ["case-ristorante-milano"]})
        blocks.append({"componente": "cta_contatto", "variante": cta, "raccordo": bridges["cta_contatto"]})
        return {"profilo": profile, "lingua": language, "confidenza": 0.85, "blocchi": blocks}


class SimulatedEmbedder:
    """Vettori per parole: testi con parole in comune risultano vicini."""

    DIMENSIONS = 256

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vector = [0.0] * self.DIMENSIONS
            for word in re.findall(r"\w+", normalize(text)):
                if len(word) < 3:
                    continue
                bucket = int(hashlib.md5(word[:6].encode()).hexdigest(), 16) % self.DIMENSIONS
                vector[bucket] += 1.0
            vectors.append(vector)
        return vectors
