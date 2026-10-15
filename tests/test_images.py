import json

import pytest
from fakes import FakeLLM, LLMError, wine_client

from quuipu.ingestion.images import describe_image, describe_images, image_id

# Contenuto finto: al modello simulato bastano dei byte, non serve un'immagine vera.
FOTO_BOTTIGLIA = b"\x89PNG finta bottiglia"
FOTO_VIGNA = b"\xff\xd8 finta vigna"


def test_describe_image_returns_record_with_stable_id(tmp_path):
    path = tmp_path / "bottiglia.png"
    path.write_bytes(FOTO_BOTTIGLIA)
    llm = FakeLLM(
        {
            "descrizione": "Bottiglia di vino rosso su un tavolo di legno.",
            "tag": ["Vino", "bottiglia", "vino", " legno "],
            "categoria": "Bottiglia",
            "confidenza": 0.92,
        }
    )
    record = describe_image(wine_client(), path, llm)

    assert record == {
        "id": image_id(FOTO_BOTTIGLIA),
        "tipo": "immagine",
        "file": "bottiglia.png",
        "lingua": "it",
        "descrizione": "Bottiglia di vino rosso su un tavolo di legno.",
        "tag": ["vino", "bottiglia", "legno"],
        "categoria": "bottiglia",
        "confidenza": 0.92,
        "revisione": {"necessaria": False, "motivi": []},
    }
    sent = llm.calls[0]
    assert sent["images"][0].mime_type == "image/png"
    assert sent["images"][0].data == FOTO_BOTTIGLIA
    assert '"vigneto"' in sent["user"] and "italiano" in sent["user"]


def test_unknown_category_and_low_confidence_go_to_review(tmp_path):
    path = tmp_path / "foto.jpg"
    path.write_bytes(FOTO_VIGNA)
    llm = FakeLLM({"descrizione": "Filari al tramonto.", "categoria": "tramonto", "confidenza": 0.5})
    record = describe_image(wine_client(), path, llm)

    assert record["categoria"] == "altro"
    assert record["revisione"]["motivi"] == [
        "confidenza 0.50 sotto la soglia 0.70",
        "categoria 'tramonto' non prevista",
    ]


def test_unsupported_format_is_rejected(tmp_path):
    path = tmp_path / "foto.bmp"
    path.write_bytes(b"BM")
    with pytest.raises(ValueError):
        describe_image(wine_client(), path, FakeLLM())


def test_describe_images_skips_duplicates_and_records_errors(tmp_path):
    folder = tmp_path / "foto"
    (folder / "sotto").mkdir(parents=True)
    (folder / "a.png").write_bytes(FOTO_BOTTIGLIA)
    (folder / "sotto" / "copia.png").write_bytes(FOTO_BOTTIGLIA)
    (folder / "b.jpg").write_bytes(FOTO_VIGNA)
    (folder / "note.txt").write_text("non è un'immagine")

    llm = FakeLLM(
        {"descrizione": "Bottiglia.", "tag": ["vino"], "categoria": "bottiglia", "confidenza": 0.9},
        LLMError("servizio non disponibile"),
    )
    out = tmp_path / "out"
    result = describe_images(wine_client(), folder, llm, out)

    assert [i["file"] for i in result["immagini"]] == ["a.png"]
    assert result["errori"] == [{"file": "b.jpg", "errore": "servizio non disponibile"}]
    assert len(llm.calls) == 2  # la copia identica non viene inviata al modello
    assert json.loads((out / "images.json").read_text(encoding="utf-8")) == result
