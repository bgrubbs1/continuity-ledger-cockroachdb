"""Application service with no update or delete surface."""

from __future__ import annotations

from .models import LedgerEvent, SearchResult
from .privacy import assert_synthetic_text
from .store import LedgerStore


class ContinuityService:
    def __init__(self, store: LedgerStore) -> None:
        self._store = store

    def record(self, event: LedgerEvent) -> bool:
        return self._store.append(event)

    def recall(self, tenant_id: str, query: str, limit: int = 3) -> list[SearchResult]:
        assert_synthetic_text(query)
        return self._store.search(tenant_id, query, limit)

