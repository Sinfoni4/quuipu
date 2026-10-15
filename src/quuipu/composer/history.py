"""Cache e registro dei page plan (specifica §7 e §13).

- Cache: i piani dei profili ricorrenti (senza domanda in chat) si riusano
  finché la base di conoscenza approvata non cambia.
- Registro: ogni piano, valido o no, viene salvato con richiesta ed esito,
  per verifica, metriche e consultazione da parte del cliente.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from quuipu.knowledge.store import APPROVED, KnowledgeStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PlanHistory:
    def __init__(self, store: KnowledgeStore) -> None:
        self.conn = store.conn

    def knowledge_version(self) -> str:
        """Impronta dei contenuti approvati: cambia se cambia ciò che l'agente può usare."""
        rows = self.conn.execute(
            "SELECT id, hash, tipo, profili, lingua FROM contents WHERE stato = ? ORDER BY id",
            (APPROVED,),
        )
        digest = hashlib.sha256()
        for row in rows:
            digest.update("|".join(str(v) for v in tuple(row)).encode("utf-8"))
        return digest.hexdigest()

    def cached(self, key: str, version: str) -> dict | None:
        row = self.conn.execute(
            "SELECT piano FROM plan_cache WHERE chiave = ? AND versione = ?", (key, version)
        ).fetchone()
        return json.loads(row["piano"]) if row else None

    def save_cache(self, key: str, version: str, plan: dict) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO plan_cache (chiave, versione, piano, creato) VALUES (?, ?, ?, ?)
                   ON CONFLICT(chiave) DO UPDATE SET
                    versione=excluded.versione, piano=excluded.piano, creato=excluded.creato""",
                (key, version, json.dumps(plan, ensure_ascii=False), _now()),
            )

    def log(
        self,
        request: dict,
        standard: bool,
        plan: dict | None,
        reasons: list[str],
        discarded: list[dict],
        from_cache: bool,
    ) -> int:
        with self.conn:
            cursor = self.conn.execute(
                """INSERT INTO plan_log (creato, richiesta, esito, piano, motivi, scartati, da_cache)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    _now(),
                    json.dumps(request, ensure_ascii=False),
                    "standard" if standard else "adattiva",
                    json.dumps(plan, ensure_ascii=False) if plan else None,
                    json.dumps(reasons, ensure_ascii=False),
                    json.dumps(discarded, ensure_ascii=False),
                    int(from_cache),
                ),
            )
        return int(cursor.lastrowid)

    def recent(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM plan_log ORDER BY id DESC LIMIT ?", (limit,))
        records = []
        for row in rows:
            record = dict(row)
            for key in ("richiesta", "piano", "motivi", "scartati"):
                record[key] = json.loads(record[key]) if record[key] else None
            record["da_cache"] = bool(record["da_cache"])
            records.append(record)
        return records
