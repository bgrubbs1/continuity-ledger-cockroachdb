from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from continuity_ledger.cockroach import SCHEMA_SQL, run_with_serialization_retry
from continuity_ledger.embedding import feature_hash
from continuity_ledger.lambda_handler import make_handler
from continuity_ledger.mcp import ManagedMCPConfig
from continuity_ledger.models import LedgerEvent
from continuity_ledger.privacy import PrivacyBoundaryError
from continuity_ledger.service import ContinuityService
from continuity_ledger.store import SQLiteLedgerStore


def event(tenant: str, incident: str, sequence: int, summary: str, key: str) -> LedgerEvent:
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


class LedgerContractTests(unittest.TestCase):
    def test_embedding_is_deterministic_and_normalized(self) -> None:
        first = feature_hash("fictional queue retry evidence")
        second = feature_hash("fictional queue retry evidence")
        self.assertEqual(first, second)
        self.assertAlmostEqual(sum(value * value for value in first), 1.0)

    def test_idempotency_and_append_only_sequence(self) -> None:
        store = SQLiteLedgerStore()
        record = event("tenant_alpha", "incident_orbit", 1, "Synthetic queue retry", "orbit_1")
        self.assertTrue(store.append(record))
        self.assertFalse(store.append(record))
        conflicting = event("tenant_alpha", "incident_orbit", 1, "Changed text", "orbit_2")
        self.assertFalse(store.append(conflicting))

    def test_search_never_crosses_tenant_boundary(self) -> None:
        store = SQLiteLedgerStore()
        store.append(event("tenant_alpha", "incident_orbit", 1, "Synthetic ingest checksum retry", "a1"))
        store.append(event("tenant_beta", "incident_harbor", 1, "Synthetic ingest checksum retry", "b1"))
        results = store.search("tenant_alpha", "ingest checksum", 5)
        self.assertEqual([result.event.tenant_id for result in results], ["tenant_alpha"])
        self.assertEqual(results[0].event.incident_id, "incident_orbit")

    def test_disk_store_survives_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "ledger.sqlite3")
            first = SQLiteLedgerStore(path)
            first.append(event("tenant_alpha", "incident_orbit", 1, "Synthetic queue retry", "a1"))
            first.close()
            second = SQLiteLedgerStore(path)
            self.assertEqual(second.search("tenant_alpha", "queue", 1)[0].event.incident_id, "incident_orbit")
            second.close()

    def test_private_markers_are_rejected(self) -> None:
        rejected = (
            "contact somebody@example.com",
            "call " + "202" + "-" + "555" + "-" + "0100",
            "host " + "192" + ".168.1.5",
            r"open C:" + r"\Users\Someone\file.txt",
            "api_key=do-not-store",
            "customer production incident",
        )
        for index, text in enumerate(rejected):
            with self.subTest(text=text), self.assertRaises(PrivacyBoundaryError):
                event("tenant_alpha", "incident_orbit", index + 1, text, f"key_{index}")


class IntegrationBoundaryTests(unittest.TestCase):
    def test_schema_has_vector_index_and_tenant_key(self) -> None:
        self.assertIn("VECTOR(32)", SCHEMA_SQL)
        self.assertIn("CREATE VECTOR INDEX", SCHEMA_SQL)
        self.assertIn("PRIMARY KEY (tenant_id, incident_id, sequence)", SCHEMA_SQL)

    def test_serialization_retry_is_bounded(self) -> None:
        class SerializationFailure(Exception):
            sqlstate = "40001"

        calls = 0
        def operation() -> str:
            nonlocal calls
            calls += 1
            if calls < 3:
                raise SerializationFailure()
            return "committed"

        with patch("continuity_ledger.cockroach.time.sleep"):
            self.assertEqual(run_with_serialization_retry(operation), "committed")
        self.assertEqual(calls, 3)

    def test_non_serialization_failure_is_not_retried(self) -> None:
        calls = 0
        def operation() -> None:
            nonlocal calls
            calls += 1
            raise RuntimeError("not retryable")
        with self.assertRaises(RuntimeError):
            run_with_serialization_retry(operation)
        self.assertEqual(calls, 1)

    def test_mcp_is_https_fail_closed_and_secret_safe(self) -> None:
        with patch.dict(os.environ, {"COCKROACH_MCP_URL": "http://example.invalid", "COCKROACH_MCP_TOKEN": "token"}, clear=True):
            with self.assertRaises(ValueError):
                ManagedMCPConfig.from_environment()
        config = ManagedMCPConfig("https://cockroachlabs.cloud/mcp", "super-secret")
        self.assertNotIn("super-secret", json.dumps(config.safe_summary()))
        self.assertTrue(config.safe_summary()["read_only"])

    def test_lambda_contract_records_and_recalls(self) -> None:
        service = ContinuityService(SQLiteLedgerStore())
        handler = make_handler(lambda: service)
        record = event("tenant_alpha", "incident_orbit", 1, "Synthetic ingest retry", "a1")
        payload = {
            "tenant_id": record.tenant_id, "incident_id": record.incident_id,
            "sequence": record.sequence, "kind": record.kind, "summary": record.summary,
            "evidence": dict(record.evidence), "idempotency_key": record.idempotency_key,
            "created_at": record.created_at,
        }
        authenticated_context = {
            "http": {"method": "POST"},
            "authorizer": {"jwt": {"claims": {"tenant_id": "tenant_alpha"}}},
        }
        created = handler(
            {"rawPath": "/events", "requestContext": authenticated_context, "body": json.dumps(payload)},
            None,
        )
        self.assertEqual(created["statusCode"], 201)
        recalled = handler(
            {
                "rawPath": "/search",
                "requestContext": authenticated_context,
                "body": json.dumps({"tenant_id": "tenant_alpha", "query": "ingest retry"}),
            },
            None,
        )
        self.assertEqual(recalled["statusCode"], 200)
        self.assertEqual(json.loads(recalled["body"])["results"][0]["incident_id"], "incident_orbit")

    def test_lambda_rejects_missing_identity_before_store_access(self) -> None:
        handler = make_handler(lambda: self.fail("unauthorized request must not access persistence"))
        response = handler(
            {
                "rawPath": "/search",
                "requestContext": {"http": {"method": "POST"}},
                "body": json.dumps({"tenant_id": "tenant_alpha", "query": "ingest retry"}),
            },
            None,
        )
        self.assertEqual(response["statusCode"], 401)

    def test_lambda_rejects_cross_tenant_spoofing(self) -> None:
        handler = make_handler(lambda: self.fail("spoofed request must not access persistence"))
        response = handler(
            {
                "rawPath": "/search",
                "requestContext": {
                    "http": {"method": "POST"},
                    "authorizer": {"jwt": {"claims": {"tenant_id": "tenant_alpha"}}},
                },
                "body": json.dumps({"tenant_id": "tenant_beta", "query": "ingest retry"}),
            },
            None,
        )
        self.assertEqual(response["statusCode"], 403)

    def test_lambda_derives_tenant_from_verified_claim(self) -> None:
        service = ContinuityService(SQLiteLedgerStore())
        handler = make_handler(lambda: service)
        record = event("tenant_alpha", "incident_orbit", 1, "Synthetic ingest retry", "a1")
        payload = {
            "incident_id": record.incident_id,
            "sequence": record.sequence,
            "kind": record.kind,
            "summary": record.summary,
            "evidence": dict(record.evidence),
            "idempotency_key": record.idempotency_key,
            "created_at": record.created_at,
        }
        response = handler(
            {
                "rawPath": "/events",
                "requestContext": {
                    "http": {"method": "POST"},
                    "authorizer": {"jwt": {"claims": {"tenant_id": "tenant_alpha"}}},
                },
                "body": json.dumps(payload),
            },
            None,
        )
        self.assertEqual(response["statusCode"], 201)
        self.assertEqual(service.recall("tenant_alpha", "ingest retry", 1)[0].event.incident_id, "incident_orbit")

    def test_health_does_not_initialize_a_backend(self) -> None:
        handler = make_handler(lambda: self.fail("health must not access persistence"))
        response = handler({"rawPath": "/healthz", "requestContext": {"http": {"method": "GET"}}}, None)
        self.assertEqual(response["statusCode"], 200)


if __name__ == "__main__":
    unittest.main()
