import json

import httpx
import pytest

from quuipu.ingestion.llm import ImageInput, LLMError, MistralClient, parse_json_object


def mistral(handler):
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return MistralClient("modello-di-prova", api_key="chiave-di-prova", http=http)


def test_parse_json_object_accepts_code_fences():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(LLMError):
        parse_json_object("[1, 2]")
    with pytest.raises(LLMError):
        parse_json_object("non è json")


def test_mistral_request_with_image():
    sent = {}

    def handler(request):
        sent["auth"] = request.headers["authorization"]
        sent["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    result = mistral(handler).complete_json("sistema", "utente", [ImageInput(b"abc", "image/png")])

    assert result == {"ok": True}
    assert sent["auth"] == "Bearer chiave-di-prova"
    body = sent["body"]
    assert body["model"] == "modello-di-prova"
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0] == {"role": "system", "content": "sistema"}
    assert body["messages"][1]["content"] == [
        {"type": "text", "text": "utente"},
        {"type": "image_url", "image_url": "data:image/png;base64,YWJj"},
    ]


def test_mistral_http_error_becomes_llm_error():
    client = mistral(lambda request: httpx.Response(429, json={"message": "rate limit"}))
    with pytest.raises(LLMError):
        client.complete_json("sistema", "utente")


def test_missing_api_key(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    with pytest.raises(LLMError):
        MistralClient("modello")
