"""Oggetti di prova condivisi tra i test."""

from quuipu.config import ClientConfig, CrawlSettings, IngestionSettings
from quuipu.ingestion.llm import LLMError


class FakeLLM:
    """Restituisce risposte preparate in ordine e registra le chiamate."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def complete_json(self, system, user, images=()):
        self.calls.append({"system": system, "user": user, "images": list(images)})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def wine_client(**ingestion):
    return ClientConfig(
        id="cantina",
        name="Cantina di prova",
        sector="agrifood",
        base_url="https://www.cantina.test/",
        languages=("it", "en"),
        crawl=CrawlSettings(delay_seconds=0),
        ingestion=IngestionSettings(
            image_categories=("bottiglia", "vigneto", "cantina", "altro"), **ingestion
        ),
    )


def _escape(text):
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages):
    """PDF minimo con testo: una lista di righe per ogni pagina."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>"]
    page_ids = [4 + 2 * i for i in range(len(pages))]
    kids = " ".join(f"{p} 0 R" for p in page_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for page_id, lines in zip(page_ids, pages):
        objects.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {page_id + 1} 0 R >>"
        )
        ops = ["BT", "/F1 12 Tf", "14 TL", "50 800 Td"]
        ops += [f"({_escape(line)}) Tj T*" for line in lines]
        ops.append("ET")
        stream = "\n".join(ops)
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")

    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


__all__ = ["FakeLLM", "LLMError", "make_pdf", "wine_client"]
