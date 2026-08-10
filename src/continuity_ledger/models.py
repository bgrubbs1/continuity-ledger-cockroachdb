"""Validated domain records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Mapping

from .embedding import feature_hash
from .privacy import assert_synthetic_text

_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


def _validated_id(label: str, value: str) -> str:
    if not _ID.fullmatch(value):
        raise ValueError(f"{label} must match {_ID.pattern}")
    return value


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    tenant_id: str
    incident_id: str
    sequence: int
    kind: str
    summary: str
    evidence: Mapping[str, str]
    idempotency_key: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        _validated_id("tenant_id", self.tenant_id)
        _validated_id("incident_id", self.incident_id)
        _validated_id("kind", self.kind)
        _validated_id("idempotency_key", self.idempotency_key)
        if self.sequence < 1:
            raise ValueError("sequence must be positive")
        datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        assert_synthetic_text(self.summary, *(f"{key} {value}" for key, value in self.evidence.items()))

    @property
    def searchable_text(self) -> str:
        pairs = " ".join(f"{key} {value}" for key, value in sorted(self.evidence.items()))
        return f"{self.kind} {self.summary} {pairs}".strip()

    @property
    def embedding(self) -> tuple[float, ...]:
        return feature_hash(self.searchable_text)


@dataclass(frozen=True, slots=True)
class SearchResult:
    event: LedgerEvent
    score: float

