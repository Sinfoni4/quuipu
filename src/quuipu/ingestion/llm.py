"""Accesso ai modelli linguistici usati nell'ingestione.

Il resto del codice dipende solo dal protocollo LLMClient, così i modelli si
possono cambiare (o sostituire con un finto nei test) senza toccare la logica.
Il modello linguistico scelto è Mistral; il modello per le immagini non è
ancora deciso e va indicato in QUUIPU_VISION_MODEL.
"""

from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from typing import Protocol, Sequence

import httpx
from dotenv import load_dotenv


class LLMError(Exception):
    pass


@dataclass(frozen=True)
class ImageInput:
    data: bytes
    mime_type: str


class LLMClient(Protocol):
    def complete_json(self, system: str, user: str, images: Sequence[ImageInput] = ()) -> dict:
        """Invia il prompt e restituisce la risposta del modello come oggetto JSON."""
        ...


def parse_json_object(text: str) -> dict:
    """Legge un oggetto JSON dalla risposta, anche se racchiuso in un blocco ```."""
    cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMError(f"risposta non in formato JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise LLMError("la risposta JSON non è un oggetto")
    return data


class MistralClient:
    API_URL = "https://api.mistral.ai/v1/chat/completions"

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        http: httpx.Client | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("MISTRAL_API_KEY", "")
        if not self.api_key:
            raise LLMError("manca MISTRAL_API_KEY")
        self.http = http or httpx.Client(timeout=timeout)

    def complete_json(self, system: str, user: str, images: Sequence[ImageInput] = ()) -> dict:
        content: str | list[dict] = user
        if images:
            content = [{"type": "text", "text": user}] + [
                {
                    "type": "image_url",
                    "image_url": f"data:{img.mime_type};base64,"
                    + base64.b64encode(img.data).decode("ascii"),
                }
                for img in images
            ]
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
        }
        try:
            response = self.http.post(
                self.API_URL,
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            response.raise_for_status()
            text = response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"chiamata a Mistral non riuscita: {exc}") from exc
        return parse_json_object(text)


def text_client() -> LLMClient:
    load_dotenv()
    return MistralClient(os.environ.get("QUUIPU_TEXT_MODEL", "mistral-small-latest"))


def vision_client() -> LLMClient:
    load_dotenv()
    model = os.environ.get("QUUIPU_VISION_MODEL", "")
    if not model:
        raise LLMError("modello per le immagini non ancora scelto: impostare QUUIPU_VISION_MODEL")
    return MistralClient(model)
