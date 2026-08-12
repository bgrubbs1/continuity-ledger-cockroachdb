"""Idempotent, evidence-producing bootstrap for an authorized managed cluster."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping

from .cockroach import CockroachLedgerStore, SCHEMA_SQL


REQUIRED_ASSERTIONS = (
    "ledger_events_table_present",
    "ledger_events_vector_index_present",
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BANNED_KEYS = re.compile(
    r"(?:connection|database_url|dsn|host|port|token|secret|password|path)", re.I
)
_BANNED_VALUES = (
    re.compile(r"postgres(?:ql)?://", re.I),
    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    re.compile(r"[A-Z]:\\", re.I),
    re.compile(r"\b(?:token|secret|password)\s*[:=]", re.I),
)


def bootstrap_managed_schema(
    connection_factory: Callable[[], object],
) -> dict[str, bool]:
    """Create the schema if needed, then verify its required durable objects.

    The operation is safe to repeat because ``SCHEMA_SQL`` uses
    ``IF NOT EXISTS`` for both the table and vector index. A separate
    connection verifies the postcondition instead of treating successful SQL
    execution as proof that the expected objects are available.
    """

    CockroachLedgerStore(connection_factory).initialize()

    connection = connection_factory()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'ledger_events'"
            )
            table_present = cursor.fetchone() is not None
            cursor.execute(
                "SELECT index_name FROM [SHOW INDEXES FROM ledger_events] "
                "WHERE index_name = 'ledger_events_embedding_idx'"
            )
            vector_index_present = cursor.fetchone() is not None
    finally:
        connection.close()

    assertions = {
        "ledger_events_table_present": table_present,
        "ledger_events_vector_index_present": vector_index_present,
    }
    if set(assertions) != set(REQUIRED_ASSERTIONS) or not all(assertions.values()):
        failed = sorted(name for name, passed in assertions.items() if not passed)
        raise RuntimeError(
            "managed schema bootstrap did not verify required objects: "
            + ", ".join(failed)
        )
    return assertions


def build_managed_schema_receipt(
    assertions: Mapping[str, bool],
    *,
    verified_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a public-safe receipt after a real managed bootstrap succeeds."""

    when = verified_at or datetime.now(timezone.utc)
    receipt: dict[str, Any] = {
        "schema_version": "1.0",
        "verified_at": when.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
        "scope": "authorized managed CockroachDB schema bootstrap",
        "managed_cloud_claimed": True,
        "data_boundary": "schema only; no tenant records inspected",
        "schema": {
            "table": "ledger_events",
            "vector_dimensions": 32,
            "vector_index": "ledger_events_embedding_idx",
            "sql_sha256": hashlib.sha256(SCHEMA_SQL.encode("utf-8")).hexdigest(),
        },
        "assertions": dict(sorted(assertions.items())),
    }
    validate_managed_schema_receipt(receipt)
    return receipt


def validate_managed_schema_receipt(receipt: Mapping[str, Any]) -> None:
    """Reject incomplete or connection-bearing managed evidence."""

    if receipt.get("managed_cloud_claimed") is not True:
        raise ValueError("managed receipt must explicitly identify its evidence scope")
    assertions = receipt.get("assertions")
    if not isinstance(assertions, Mapping) or set(assertions) != set(REQUIRED_ASSERTIONS):
        raise ValueError("managed receipt requires the exact bootstrap assertions")
    if any(value is not True for value in assertions.values()):
        raise ValueError("managed receipt may record only a fully passing bootstrap")
    schema = receipt.get("schema")
    if not isinstance(schema, Mapping) or not _SHA256.fullmatch(
        str(schema.get("sql_sha256", ""))
    ):
        raise ValueError("managed receipt requires a schema SHA-256")

    def inspect(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if _BANNED_KEYS.search(str(key)):
                    raise ValueError(f"managed receipt contains prohibited key: {key}")
                inspect(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                inspect(child)
        elif isinstance(value, str):
            if any(pattern.search(value) for pattern in _BANNED_VALUES):
                raise ValueError("managed receipt contains private connection material")

    inspect(receipt)


def write_managed_schema_receipt(path: Path, receipt: Mapping[str, Any]) -> str:
    """Write, reopen, and validate a canonical managed-bootstrap receipt."""

    validate_managed_schema_receipt(receipt)
    payload = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    validate_managed_schema_receipt(json.loads(path.read_text(encoding="utf-8")))
    return hashlib.sha256(payload).hexdigest()
