"""Local reference store used to test the public storage contract."""

from __future__ import annotations

import json
import sqlite3
from typing import Protocol

from .embedding import cosine, feature_hash
from .models import LedgerEvent, SearchResult


class LedgerStore(Protocol):
    def append(self, event: LedgerEvent) -> bool: ...
    def search(self, tenant_id: str, query: str, limit: int = 3) -> list[SearchResult]: ...


class SQLiteLedgerStore:
    """A credential-free reference implementation, not the cloud backend."""

    def __init__(self, path: str = ":memory:") -> None:
        self._connection = sqlite3.connect(path)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger_events (
                tenant_id TEXT NOT NULL,
                incident_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                kind TEXT NOT NULL,
                summary TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                created_at TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, incident_id, sequence),
                UNIQUE (tenant_id, idempotency_key)
            )
            """
        )

    def append(self, event: LedgerEvent) -> bool:
        try:
            self._connection.execute(
                """INSERT INTO ledger_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.tenant_id,
                    event.incident_id,
                    event.sequence,
                    event.kind,
                    event.summary,
                    json.dumps(dict(event.evidence), sort_keys=True, separators=(",", ":")),
                    event.idempotency_key,
                    event.created_at,
                    json.dumps(event.embedding, separators=(",", ":")),
                ),
            )
            self._connection.commit()
            return True
        except sqlite3.IntegrityError:
            self._connection.rollback()
            return False

    def search(self, tenant_id: str, query: str, limit: int = 3) -> list[SearchResult]:
        if limit < 1 or limit > 20:
            raise ValueError("limit must be between 1 and 20")
        query_embedding = feature_hash(query)
        rows = self._connection.execute(
            """SELECT tenant_id, incident_id, sequence, kind, summary, evidence_json,
                      idempotency_key, created_at, embedding_json
               FROM ledger_events WHERE tenant_id = ?""",
            (tenant_id,),
        ).fetchall()
        ranked: list[SearchResult] = []
        for row in rows:
            event = LedgerEvent(
                tenant_id=row[0], incident_id=row[1], sequence=row[2], kind=row[3],
                summary=row[4], evidence=json.loads(row[5]), idempotency_key=row[6], created_at=row[7],
            )
            stored_embedding = tuple(json.loads(row[8]))
            ranked.append(SearchResult(event=event, score=cosine(query_embedding, stored_embedding)))
        ranked.sort(key=lambda result: (-result.score, result.event.incident_id, result.event.sequence))
        return ranked[:limit]

    def close(self) -> None:
        self._connection.close()

