"""CockroachDB persistence adapter. Network use requires owner authorization."""

from __future__ import annotations

import json
import time
from typing import Callable, TypeVar

from .embedding import feature_hash, vector_literal
from .models import LedgerEvent, SearchResult

T = TypeVar("T")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ledger_events (
    tenant_id STRING NOT NULL,
    incident_id STRING NOT NULL,
    sequence INT8 NOT NULL,
    kind STRING NOT NULL,
    summary STRING NOT NULL,
    evidence JSONB NOT NULL,
    idempotency_key STRING NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    embedding VECTOR(32) NOT NULL,
    PRIMARY KEY (tenant_id, incident_id, sequence),
    UNIQUE (tenant_id, idempotency_key)
);
CREATE VECTOR INDEX IF NOT EXISTS ledger_events_embedding_idx
ON ledger_events (tenant_id, embedding);
""".strip()


def run_with_serialization_retry(operation: Callable[[], T], attempts: int = 4) -> T:
    """Retry only CockroachDB serialization failures (SQLSTATE 40001)."""

    for attempt in range(attempts):
        try:
            return operation()
        except Exception as exc:
            if getattr(exc, "sqlstate", None) != "40001" or attempt == attempts - 1:
                raise
            time.sleep(0.01 * (2**attempt))
    raise AssertionError("unreachable")


class CockroachLedgerStore:
    def __init__(self, connection_factory: Callable[[], object]) -> None:
        self._connection_factory = connection_factory

    def initialize(self) -> None:
        connection = self._connection_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(SCHEMA_SQL)
            connection.commit()
        finally:
            connection.close()

    def append(self, event: LedgerEvent) -> bool:
        def operation() -> bool:
            connection = self._connection_factory()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO ledger_events
                        (tenant_id, incident_id, sequence, kind, summary, evidence,
                         idempotency_key, created_at, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s::JSONB, %s, %s, %s::VECTOR)
                        ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
                        RETURNING tenant_id
                        """,
                        (event.tenant_id, event.incident_id, event.sequence, event.kind,
                         event.summary, json.dumps(dict(event.evidence)), event.idempotency_key,
                         event.created_at, vector_literal(event.embedding)),
                    )
                    inserted = cursor.fetchone() is not None
                connection.commit()
                return inserted
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

        return run_with_serialization_retry(operation)

    def search(self, tenant_id: str, query: str, limit: int = 3) -> list[SearchResult]:
        if limit < 1 or limit > 20:
            raise ValueError("limit must be between 1 and 20")
        connection = self._connection_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT tenant_id, incident_id, sequence, kind, summary, evidence,
                           idempotency_key, created_at,
                           1 - (embedding <=> %s::VECTOR) AS score
                    FROM ledger_events
                    WHERE tenant_id = %s
                    ORDER BY embedding <=> %s::VECTOR
                    LIMIT %s
                    """,
                    (vector_literal(feature_hash(query)), tenant_id,
                     vector_literal(feature_hash(query)), limit),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        return [
            SearchResult(
                event=LedgerEvent(
                    tenant_id=row[0], incident_id=row[1], sequence=row[2], kind=row[3],
                    summary=row[4], evidence=row[5], idempotency_key=row[6],
                    created_at=row[7].isoformat() if hasattr(row[7], "isoformat") else str(row[7]),
                ),
                score=float(row[8]),
            )
            for row in rows
        ]


def psycopg_connection_factory(database_url: str) -> Callable[[], object]:
    if not database_url:
        raise ValueError("DATABASE_URL is required")
    import psycopg  # Optional cloud dependency; never imported by local tests.

    return lambda: psycopg.connect(database_url)

