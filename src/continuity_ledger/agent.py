"""Evidence-first agent loop backed by the append-only continuity ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib

from .models import LedgerEvent, SearchResult
from .service import ContinuityService


@dataclass(frozen=True, slots=True)
class AgentOutcome:
    """A reversible action plus the durable evidence that justified it."""

    action: str
    rationale: str
    citations: tuple[str, ...]
    recalled_count: int
    observation_recorded: bool
    decision_recorded: bool


class ContinuityAgent:
    """Retrieve prior memory, choose a bounded action, and record the decision.

    This is deliberately a deterministic policy agent, not an LLM.  Every
    non-abstaining action is read-only/reversible and cites tenant-scoped
    CockroachDB memory.  The observation and decision are appended after
    retrieval so the current input cannot cite itself as prior evidence.
    """

    def __init__(self, service: ContinuityService, *, recall_limit: int = 3) -> None:
        if recall_limit < 1 or recall_limit > 20:
            raise ValueError("recall_limit must be between 1 and 20")
        self._service = service
        self._recall_limit = recall_limit

    def run(
        self,
        *,
        tenant_id: str,
        incident_id: str,
        sequence: int,
        observation: str,
        idempotency_key: str,
        created_at: str | None = None,
    ) -> AgentOutcome:
        recalled = self._service.recall(
            tenant_id,
            observation,
            self._recall_limit,
        )
        action, rationale, supporting = _choose_action(recalled)
        citations = tuple(
            f"{item.event.incident_id}:{item.event.sequence}" for item in supporting
        )
        timestamp = created_at or datetime.now(timezone.utc).isoformat()

        observation_event = LedgerEvent(
            tenant_id=tenant_id,
            incident_id=incident_id,
            sequence=sequence,
            kind="observation",
            summary=observation,
            evidence={"source": "synthetic agent input", "state": "observed"},
            idempotency_key=idempotency_key,
            created_at=timestamp,
        )
        observation_recorded = self._service.record(observation_event)

        decision_key = "decision_" + hashlib.sha256(
            f"{tenant_id}:{idempotency_key}".encode("utf-8")
        ).hexdigest()[:24]
        decision_event = LedgerEvent(
            tenant_id=tenant_id,
            incident_id=incident_id,
            sequence=sequence + 1,
            kind="decision",
            summary=f"Synthetic agent action {action}. {rationale}",
            evidence={
                "source": "deterministic memory policy",
                "citations": ",".join(citations) if citations else "none",
            },
            idempotency_key=decision_key,
            created_at=timestamp,
        )
        decision_recorded = self._service.record(decision_event)

        return AgentOutcome(
            action=action,
            rationale=rationale,
            citations=citations,
            recalled_count=len(recalled),
            observation_recorded=observation_recorded,
            decision_recorded=decision_recorded,
        )


def _choose_action(
    recalled: list[SearchResult],
) -> tuple[str, str, tuple[SearchResult, ...]]:
    if not recalled:
        return (
            "request_more_evidence",
            "No prior tenant memory supports a more specific action.",
            (),
        )

    top = next((item for item in recalled if item.event.kind == "handoff"), None)
    if top is None:
        return (
            "request_more_evidence",
            "Retrieved memory contains no reviewed handoff evidence.",
            (),
        )
    searchable = top.event.searchable_text.lower()
    if "ingest" in searchable or "checksum" in searchable:
        action = "inspect_ingest_validation"
        rationale = "Prior memory links this symptom to the synthetic ingest path."
    elif any(word in searchable for word in ("transcode", "worker", "capacity")):
        action = "inspect_transcode_capacity"
        rationale = "Prior memory links this symptom to synthetic worker capacity."
    elif "publish" in searchable or "review" in searchable:
        action = "verify_publish_status"
        rationale = "Prior memory supports a fresh synthetic publish-status check."
    else:
        return (
            "request_more_evidence",
            "Retrieved memory is not specific enough for a bounded action.",
            (),
        )
    return action, rationale, (top,)
