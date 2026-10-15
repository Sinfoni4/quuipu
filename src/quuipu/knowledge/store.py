"""Archivio dei contenuti del cliente, con stato di approvazione.

Ogni cliente ha il proprio file di database, quindi i dati dei clienti non si
mescolano mai (multi-tenant per separazione fisica). Per il PoC si usa SQLite;
lo schema è pensato per passare a PostgreSQL con pgvector.

Stato di un contenuto:
- "escluso": il cliente ha deciso che l'agente non deve usarlo;
- "approvato": confermato dal cliente, oppure estratto senza dubbi;
- "da_rivedere": in coda di revisione, l'agente non lo usa.
Una decisione del cliente resta valida finché il contenuto non cambia; un
contenuto escluso resta escluso anche se cambia.
"""

from __future__ import annotations

import json
import sqlite3
from array import array
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from quuipu.config import ClientConfig, data_dir

APPROVED, TO_REVIEW, EXCLUDED = "approvato", "da_rivedere", "escluso"
DECISIONS = (APPROVED, EXCLUDED)

SCHEMA = """
CREATE TABLE IF NOT EXISTS contents (
    id          TEXT PRIMARY KEY,
    fonte       TEXT NOT NULL,
    tipo        TEXT NOT NULL,
    lingua      TEXT NOT NULL DEFAULT '',
    titolo      TEXT NOT NULL DEFAULT '',
    testo       TEXT NOT NULL DEFAULT '',
    url         TEXT NOT NULL DEFAULT '',
    dati        TEXT NOT NULL DEFAULT '{}',
    profili     TEXT NOT NULL DEFAULT '[]',
    motivi      TEXT NOT NULL DEFAULT '[]',
    hash        TEXT NOT NULL,
    decisione   TEXT,
    stato       TEXT NOT NULL,
    aggiornato  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY,
    content_id  TEXT NOT NULL REFERENCES contents(id) ON DELETE CASCADE,
    hash        TEXT NOT NULL,
    testo       TEXT NOT NULL,
    vettore     BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_content ON chunks(content_id);
CREATE TABLE IF NOT EXISTS plan_cache (
    chiave      TEXT PRIMARY KEY,
    versione    TEXT NOT NULL,
    piano       TEXT NOT NULL,
    creato      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plan_log (
    id          INTEGER PRIMARY KEY,
    creato      TEXT NOT NULL,
    richiesta   TEXT NOT NULL,
    esito       TEXT NOT NULL,
    piano       TEXT,
    motivi      TEXT NOT NULL,
    scartati    TEXT NOT NULL,
    da_cache    INTEGER NOT NULL
);
"""


@dataclass
class Content:
    id: str
    fonte: str
    tipo: str
    hash: str
    lingua: str = ""
    titolo: str = ""
    testo: str = ""
    url: str = ""
    dati: dict = field(default_factory=dict)
    profili: list[str] = field(default_factory=list)
    motivi: list[str] = field(default_factory=list)


def state_for(decision: str | None, reasons: list[str]) -> str:
    if decision in DECISIONS:
        return decision
    return TO_REVIEW if reasons else APPROVED


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def pack_vector(vector: list[float]) -> bytes:
    return array("f", vector).tobytes()


def unpack_vector(blob: bytes) -> list[float]:
    values = array("f")
    values.frombytes(blob)
    return values.tolist()


class KnowledgeStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        # WAL: scritture più veloci e letture non bloccate mentre si scrive il registro.
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.executescript(SCHEMA)

    @classmethod
    def for_client(cls, client: ClientConfig, base_dir: Path | None = None) -> "KnowledgeStore":
        return cls((base_dir or data_dir() / client.id) / "knowledge.db")

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "KnowledgeStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- contenuti -------------------------------------------------------

    def sync(self, contents: list[Content]) -> dict[str, list[str]]:
        """Allinea l'archivio all'elenco completo dei contenuti attuali."""
        existing = {
            row["id"]: row
            for row in self.conn.execute("SELECT id, hash, decisione FROM contents")
        }
        report: dict[str, list[str]] = {"nuovi": [], "modificati": [], "invariati": [], "rimossi": []}
        current_ids = set()
        with self.conn:
            for c in contents:
                current_ids.add(c.id)
                old = existing.get(c.id)
                if old is None:
                    decision = None
                    report["nuovi"].append(c.id)
                elif old["hash"] != c.hash:
                    # Contenuto cambiato: l'approvazione va ridata, l'esclusione resta.
                    decision = EXCLUDED if old["decisione"] == EXCLUDED else None
                    report["modificati"].append(c.id)
                else:
                    decision = old["decisione"]
                    report["invariati"].append(c.id)
                self.conn.execute(
                    """INSERT INTO contents
                       (id, fonte, tipo, lingua, titolo, testo, url, dati, profili, motivi,
                        hash, decisione, stato, aggiornato)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                        fonte=excluded.fonte, tipo=excluded.tipo, lingua=excluded.lingua,
                        titolo=excluded.titolo, testo=excluded.testo, url=excluded.url,
                        dati=excluded.dati, profili=excluded.profili, motivi=excluded.motivi,
                        hash=excluded.hash, decisione=excluded.decisione, stato=excluded.stato,
                        aggiornato=excluded.aggiornato""",
                    (
                        c.id, c.fonte, c.tipo, c.lingua, c.titolo, c.testo, c.url,
                        json.dumps(c.dati, ensure_ascii=False),
                        json.dumps(c.profili, ensure_ascii=False),
                        json.dumps(c.motivi, ensure_ascii=False),
                        c.hash, decision, state_for(decision, c.motivi), _now(),
                    ),
                )
            for content_id in existing.keys() - current_ids:
                self.conn.execute("DELETE FROM contents WHERE id = ?", (content_id,))
                report["rimossi"].append(content_id)
        return report

    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        record = dict(row)
        for key in ("dati", "profili", "motivi"):
            record[key] = json.loads(record[key])
        return record

    def get(self, content_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM contents WHERE id = ?", (content_id,)).fetchone()
        return self._row(row) if row else None

    def list(
        self, stato: str | None = None, tipo: str | None = None, profilo: str | None = None
    ) -> list[dict]:
        query, params = "SELECT * FROM contents WHERE 1=1", []
        if stato:
            query += " AND stato = ?"
            params.append(stato)
        if tipo:
            query += " AND tipo = ?"
            params.append(tipo)
        rows = [self._row(r) for r in self.conn.execute(query + " ORDER BY fonte, id", params)]
        return [r for r in rows if not profilo or profilo in r["profili"]]

    def decide(self, content_id: str, decision: str | None) -> bool:
        """Registra la decisione del cliente: approvato, escluso o None per annullarla."""
        if decision is not None and decision not in DECISIONS:
            raise ValueError(f"decisione non valida: {decision}")
        row = self.conn.execute("SELECT motivi FROM contents WHERE id = ?", (content_id,)).fetchone()
        if row is None:
            return False
        with self.conn:
            self.conn.execute(
                "UPDATE contents SET decisione = ?, stato = ?, aggiornato = ? WHERE id = ?",
                (decision, state_for(decision, json.loads(row["motivi"])), _now(), content_id),
            )
        return True

    def counts(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT stato, COUNT(*) AS n FROM contents GROUP BY stato")
        return {r["stato"]: r["n"] for r in rows}

    # --- indice semantico -----------------------------------------------

    def contents_to_index(self) -> list[dict]:
        """Contenuti senza vettori aggiornati (nuovi o cambiati dall'ultima indicizzazione)."""
        rows = self.conn.execute(
            """SELECT c.* FROM contents c
               WHERE NOT EXISTS (SELECT 1 FROM chunks k
                                 WHERE k.content_id = c.id AND k.hash = c.hash)
               ORDER BY c.id"""
        )
        return [self._row(r) for r in rows]

    def replace_chunks(
        self, content_id: str, content_hash: str, chunks: list[tuple[str, list[float]]]
    ) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM chunks WHERE content_id = ?", (content_id,))
            self.conn.executemany(
                "INSERT INTO chunks (content_id, hash, testo, vettore) VALUES (?, ?, ?, ?)",
                [(content_id, content_hash, text, pack_vector(vec)) for text, vec in chunks],
            )

    def chunks(self, stati: tuple[str, ...] = (APPROVED,)) -> list[dict]:
        placeholders = ", ".join("?" for _ in stati)
        rows = self.conn.execute(
            f"""SELECT k.content_id, k.testo, k.vettore FROM chunks k
                JOIN contents c ON c.id = k.content_id
                WHERE c.stato IN ({placeholders})""",
            stati,
        )
        return [
            {"content_id": r["content_id"], "testo": r["testo"], "vettore": unpack_vector(r["vettore"])}
            for r in rows
        ]
