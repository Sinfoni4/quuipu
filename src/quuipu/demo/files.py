"""Generatori di file di prova: PDF con testo e immagini PNG a tinta unita."""

from __future__ import annotations

import struct
import zlib


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages: list[list[str]]) -> bytes:
    """PDF minimo con testo: una lista di righe (senza accenti) per ogni pagina."""
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


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def solid_png(rgb: tuple[int, int, int], width: int = 480, height: int = 300) -> bytes:
    """PNG a tinta unita, con una leggera sfumatura verticale."""
    rows = []
    for y in range(height):
        shade = 1.0 - 0.35 * y / height
        pixel = bytes(int(c * shade) for c in rgb)
        rows.append(b"\x00" + pixel * width)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + _chunk(b"IEND", b"")
    )


def png_color(data: bytes) -> tuple[int, int, int] | None:
    """Colore del primo pixel di un PNG generato da solid_png."""
    position = data.find(b"IDAT")
    if position < 4:
        return None
    length = struct.unpack(">I", data[position - 4:position])[0]
    try:
        raw = zlib.decompress(data[position + 4:position + 4 + length])
    except zlib.error:
        return None
    return raw[1], raw[2], raw[3]
