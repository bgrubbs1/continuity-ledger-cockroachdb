#!/usr/bin/env python3
"""Reproduce the synthetic CockroachDB vector contract in a disposable container."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import uuid
from typing import Any, Callable, Mapping

from continuity_ledger.cockroach import CockroachLedgerStore, run_with_serialization_retry
from continuity_ledger.embedding import cosine, feature_hash
from continuity_ledger.models import LedgerEvent


REQUIRED_ASSERTIONS = (
    "schema_initialized",
    "vector_index_present",
    "idempotent_replay_blocked",
    "sequence_conflict_blocked",
    "tenant_isolation_preserved",
    "similarity_result_verified",
    "serialization_retry_verified",
)
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_BANNED_KEYS = re.compile(r"(?:connection|dsn|host|port|token|secret|password|path)", re.I)
_BANNED_VALUES = (
    re.compile(r"postgres(?:ql)?://", re.I),
    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    re.compile(r"[A-Z]:\\", re.I),
    re.compile(r"\b(?:token|secret|password)\s*[:=]", re.I),
)


def build_receipt(
    *,
    image_reference: str,
    image_digest: str,
    assertions: Mapping[str, bool],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "verified_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "scope": "local disposable CockroachDB vector contract",
        "managed_cloud_claimed": False,
        "data_boundary": "deliberately fictional events only",
        "image": {"reference": image_reference, "digest": image_digest},
        "contract": {
            "table": "ledger_events",
            "vector_dimensions": 32,
            "vector_index": "ledger_events_embedding_idx",
            "tenant_partition": "tenant_id",
        },
        "assertions": dict(sorted(assertions.items())),
    }


def validate_receipt(receipt: Mapping[str, Any]) -> None:
    image = receipt.get("image")
    if not isinstance(image, Mapping) or not _DIGEST.fullmatch(str(image.get("digest", ""))):
        raise ValueError("receipt requires a pinned sha256 image digest")
    assertions = receipt.get("assertions")
    if not isinstance(assertions, Mapping) or not assertions:
        raise ValueError("receipt requires assertions")
    if any(value is not True for value in assertions.values()):
        raise ValueError("receipt may record only a fully passing contract")

    def inspect(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if _BANNED_KEYS.search(str(key)):
                    raise ValueError(f"receipt contains prohibited key: {key}")
                inspect(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                inspect(child)
        elif isinstance(value, str):
            for pattern in _BANNED_VALUES:
                if pattern.search(value):
                    raise ValueError("receipt contains connection or private material")

    inspect(receipt)


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, capture_output=True, text=True)


def _image_digest(image: str) -> str:
    result = _run(["docker", "image", "inspect", image, "--format", "{{json .RepoDigests}}"])
    digests = json.loads(result.stdout.strip())
    if digests:
        digest = str(digests[0]).rsplit("@", 1)[-1]
    else:
        fallback = _run(["docker", "image", "inspect", image, "--format", "{{.Id}}"])
        digest = fallback.stdout.strip()
    if not _DIGEST.fullmatch(digest):
        raise RuntimeError("container image does not expose a sha256 digest")
    return digest


def _wait_until_ready(connection_factory: Callable[[], Any], timeout_seconds: int = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            connection = connection_factory()
            connection.close()
            return
        except Exception:
            pass
        time.sleep(1)
    raise TimeoutError("disposable CockroachDB container did not become ready")


def _mapped_sql_port(container: str) -> int:
    result = _run(["docker", "port", container, "26257/tcp"])
    endpoint = result.stdout.strip().splitlines()[0]
    port = int(endpoint.rsplit(":", 1)[-1])
    if port < 1 or port > 65535:
        raise RuntimeError("Docker returned an invalid ephemeral SQL port")
    return port


def _event(tenant: str, incident: str, sequence: int, summary: str, key: str) -> LedgerEvent:
    return LedgerEvent(
        tenant_id=tenant,
        incident_id=incident,
        sequence=sequence,
        kind="handoff",
        summary=summary,
        evidence={"source": "fictional simulator", "state": "reviewed"},
        idempotency_key=key,
        created_at="2026-08-10T00:00:00+00:00",
    )


def verify_contract(image: str) -> tuple[str, dict[str, bool]]:
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - environment diagnostic
        raise RuntimeError("install the project cloud extra before running this verifier") from exc

    digest = _image_digest(image)
    container = f"continuity-ledger-verify-{uuid.uuid4().hex[:12]}"
    database = "ledger"
    user = "ledger"
    password = secrets.token_hex(24)
    started = False
    try:
        _run([
            "docker", "run", "--detach", "--rm", "--name", container,
            "--publish", "127.0.0.1::26257",
            "--env", f"COCKROACH_DATABASE={database}",
            "--env", f"COCKROACH_USER={user}",
            "--env", f"COCKROACH_PASSWORD={password}",
            image, "start-single-node", "--http-addr=0.0.0.0:8080",
            "--store=type=mem,size=1GiB",
        ])
        started = True
        port = _mapped_sql_port(container)
        connection_factory = lambda: psycopg.connect(
            host="127.0.0.1",
            port=port,
            dbname=database,
            user=user,
            password=password,
            sslmode="require",
            connect_timeout=2,
        )
        _wait_until_ready(connection_factory)
        store = CockroachLedgerStore(connection_factory)
        store.initialize()

        alpha = _event("tenant_alpha", "incident_orbit", 1, "Synthetic ingest checksum retry", "alpha_1")
        beta = _event("tenant_beta", "incident_harbor", 1, "Synthetic ingest checksum retry", "beta_1")
        inserted = store.append(alpha)
        replay_blocked = not store.append(alpha)
        store.append(beta)

        sequence_conflict_blocked = False
        try:
            store.append(_event("tenant_alpha", "incident_orbit", 1, "Synthetic changed text", "alpha_2"))
        except Exception as exc:
            sequence_conflict_blocked = getattr(exc, "sqlstate", None) == "23505"

        query = "ingest checksum retry"
        results = store.search("tenant_alpha", query, 5)
        tenant_isolation = bool(results) and all(result.event.tenant_id == "tenant_alpha" for result in results)
        expected_score = cosine(alpha.embedding, feature_hash(query))
        similarity_verified = (
            bool(results)
            and results[0].event.incident_id == "incident_orbit"
            and abs(results[0].score - expected_score) < 1e-6
        )

        with connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT index_name FROM [SHOW INDEXES FROM ledger_events] "
                "WHERE index_name = 'ledger_events_embedding_idx'"
            )
            vector_index_present = cursor.fetchone() is not None

        class SerializationFailure(Exception):
            sqlstate = "40001"

        attempts = 0

        def retry_probe() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise SerializationFailure()
            return "committed"

        retry_verified = run_with_serialization_retry(retry_probe) == "committed" and attempts == 3
        assertions = {
            "schema_initialized": inserted,
            "vector_index_present": vector_index_present,
            "idempotent_replay_blocked": replay_blocked,
            "sequence_conflict_blocked": sequence_conflict_blocked,
            "tenant_isolation_preserved": tenant_isolation,
            "similarity_result_verified": similarity_verified,
            "serialization_retry_verified": retry_verified,
        }
        if set(assertions) != set(REQUIRED_ASSERTIONS) or not all(assertions.values()):
            failed = sorted(key for key, value in assertions.items() if not value)
            diagnostics = {
                "fictional_result_ids": [result.event.incident_id for result in results],
                "scores": [round(result.score, 9) for result in results],
            }
            raise AssertionError(
                f"CockroachDB contract failed: {', '.join(failed)}; "
                f"diagnostics={json.dumps(diagnostics, sort_keys=True)}"
            )
        return digest, assertions
    finally:
        if started:
            _run(["docker", "rm", "--force", container], check=False)


def write_receipt(path: Path, receipt: Mapping[str, Any]) -> str:
    validate_receipt(receipt)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(payload)
    validate_receipt(json.loads(path.read_text(encoding="utf-8")))
    return hashlib.sha256(payload).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="cockroachdb/cockroach:v26.2.3")
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path("artifacts/public/local-cockroach-contract.json"),
    )
    args = parser.parse_args(argv)

    digest, assertions = verify_contract(args.image)
    receipt = build_receipt(image_reference=args.image, image_digest=digest, assertions=assertions)
    receipt_hash = write_receipt(args.receipt, receipt)
    print(f"PASS: {len(assertions)} CockroachDB assertions; receipt sha256={receipt_hash}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
