"""Sessioni dei visitatori, solo in memoria (specifica §6 e §12).

Nessun cookie e nessun dato persistente: la sessione è identificata da un
codice casuale che il widget tiene finché la scheda del browser è aperta, e
scade dopo un periodo di inattività. Riavviando il server le sessioni spariscono.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from quuipu.visitor.profile import Signals

SESSION_TTL_SECONDS = 30 * 60
MAX_SESSIONS = 50_000


@dataclass
class Session:
    id: str
    client_id: str
    signals: Signals = field(default_factory=Signals)
    last_seen: float = 0.0


class SessionStore:
    def __init__(
        self,
        ttl: float = SESSION_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        max_sessions: int = MAX_SESSIONS,
    ) -> None:
        self.ttl = ttl
        self.clock = clock
        self.max_sessions = max_sessions
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def _purge(self, now: float) -> None:
        expired = [sid for sid, s in self._sessions.items() if now - s.last_seen > self.ttl]
        for sid in expired:
            del self._sessions[sid]
        # Con troppe sessioni aperte si eliminano le più vecchie.
        overflow = len(self._sessions) - self.max_sessions
        if overflow > 0:
            for sid in sorted(self._sessions, key=lambda s: self._sessions[s].last_seen)[:overflow]:
                del self._sessions[sid]

    def get_or_create(self, client_id: str, session_id: str | None) -> tuple[Session, bool]:
        """(sessione, True se nuova). Un codice scaduto o di un altro cliente ne crea una nuova."""
        now = self.clock()
        with self._lock:
            self._purge(now)
            session = self._sessions.get(session_id or "")
            created = session is None or session.client_id != client_id
            if created:
                session = Session(id=secrets.token_urlsafe(16), client_id=client_id)
                self._sessions[session.id] = session
            session.last_seen = now
            return session, created

    def __len__(self) -> int:
        return len(self._sessions)
