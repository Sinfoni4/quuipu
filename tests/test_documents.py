import json

from fakes import FakeLLM, LLMError, make_pdf, wine_client

from quuipu.ingestion.documents import (
    build_product,
    chunk_pages,
    extract_pdf_pages,
    parse_documents,
    product_id,
)
from quuipu.ingestion.review import found_in_source

CATALOGO = [
    [
        "Catalogo 2026",
        "Prosecco DOC Treviso Brut",
        "Vitigno: Glera",
        "Gradazione: 11,5% vol",
        "Formato: 0,75 l",
    ],
    [
        "Chianti Classico DOCG",
        "Vitigno: Sangiovese",
        "Affinamento: 12 mesi in botte",
        "Certificazione: Biologico",
    ],
]


def write_catalog(folder):
    path = folder / "catalogo.pdf"
    path.write_bytes(make_pdf(CATALOGO))
    return path


def test_extract_pdf_pages(tmp_path):
    pages = extract_pdf_pages(write_catalog(tmp_path))
    assert len(pages) == 2
    assert "Prosecco DOC Treviso Brut" in pages[0]
    assert "Sangiovese" in pages[1]


def test_chunk_pages_groups_until_limit_and_skips_empty_pages():
    assert chunk_pages(["aaa", "", "bbb"], max_chars=10) == [(1, 3, "aaa\n\nbbb")]
    assert chunk_pages(["aaaaaa", "bbbbbb"], max_chars=10) == [(1, 1, "aaaaaa"), (2, 2, "bbbbbb")]
    assert chunk_pages(["", ""]) == []


def test_found_in_source_accepts_numbers_with_different_formatting():
    text = "Gradazione: 11,5% vol\nFormato: 0,75 l"
    assert found_in_source("11,5% vol", text)
    assert found_in_source("11.5 %", text)
    assert not found_in_source("14% vol", text)
    assert not found_in_source("Barolo", text)


def test_product_with_values_from_document_still_needs_confirmation_of_specs():
    text = "\n".join(CATALOGO[0])
    raw = {
        "nome": "Prosecco DOC Treviso Brut",
        "categoria": "spumante",
        "specifiche": {"Vitigno": "Glera", "Gradazione": "11,5% vol"},
        "confidenza": 0.9,
    }
    product = build_product(raw, "catalogo.pdf", (1, 1), text, threshold=0.7)
    assert product["id"] == product_id("catalogo.pdf", "Prosecco DOC Treviso Brut")
    assert product["documenti"] == ["catalogo.pdf"]
    assert product["revisione"] == {
        "necessaria": True,
        "motivi": ["specifiche tecniche da confermare"],
    }


def test_product_without_specs_and_high_confidence_needs_no_review():
    product = build_product(
        {"nome": "Catalogo 2026", "confidenza": 0.95}, "catalogo.pdf", (1, 1), "Catalogo 2026", 0.7
    )
    assert product["revisione"] == {"necessaria": False, "motivi": []}


def test_invented_values_and_low_confidence_are_flagged():
    text = "\n".join(CATALOGO[0])
    raw = {
        "nome": "Prosecco DOC Treviso Brut",
        "specifiche": {"Gradazione": "14% vol"},
        "prezzo": "9,90 euro",
        "confidenza": 0.4,
    }
    reasons = build_product(raw, "catalogo.pdf", (1, 1), text, 0.7)["revisione"]["motivi"]
    assert reasons == [
        "confidenza 0.40 sotto la soglia 0.70",
        "specifica 'Gradazione: 14% vol' non trovata nel documento",
        "prezzo '9,90 euro' non trovato nel documento",
        "prezzo da confermare",
        "specifiche tecniche da confermare",
    ]


def test_product_without_name_is_discarded():
    assert build_product({"categoria": "vino"}, "c.pdf", (1, 1), "", 0.7) is None


def test_parse_documents_end_to_end(tmp_path):
    docs = tmp_path / "cartella"
    docs.mkdir()
    write_catalog(docs)
    (docs / "rotto.pdf").write_bytes(b"non sono un pdf")

    llm = FakeLLM(
        {
            "prodotti": [
                {
                    "nome": "Prosecco DOC Treviso Brut",
                    "categoria": "spumante",
                    "specifiche": {"Vitigno": "Glera"},
                    "confidenza": 0.9,
                },
                {
                    "nome": "Chianti Classico DOCG",
                    "categoria": "rosso",
                    "specifiche": {"Vitigno": "Sangiovese"},
                    "certificazioni": ["Biologico"],
                    "confidenza": 0.85,
                },
                "voce non valida",
            ]
        }
    )
    out = tmp_path / "out"
    result = parse_documents(wine_client(), docs, llm, out)

    assert [p["nome"] for p in result["prodotti"]] == [
        "Prosecco DOC Treviso Brut",
        "Chianti Classico DOCG",
    ]
    assert result["prodotti"][1]["certificazioni"] == ["Biologico"]
    assert result["da_rivedere"] == 2
    assert len(llm.calls) == 1  # il PDF corto entra in un solo blocco
    assert "Cantina di prova" in llm.calls[0]["user"]
    assert "Sangiovese" in llm.calls[0]["user"]

    by_file = {d["file"]: d for d in result["documenti"]}
    assert by_file["catalogo.pdf"]["prodotti"] == 2
    assert by_file["rotto.pdf"]["errori"][0].startswith("PDF non leggibile")

    saved = json.loads((out / "products.json").read_text(encoding="utf-8"))
    assert saved == result


def test_model_error_is_recorded_and_does_not_stop_the_run(tmp_path):
    write_catalog(tmp_path)
    result = parse_documents(wine_client(), tmp_path, FakeLLM(LLMError("timeout")), tmp_path / "out")
    assert result["prodotti"] == []
    assert result["documenti"][0]["errori"] == ["pagine 1-2: timeout"]
