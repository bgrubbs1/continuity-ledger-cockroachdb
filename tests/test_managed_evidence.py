from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from continuity_ledger.managed_bootstrap import REQUIRED_ASSERTIONS
from continuity_ledger.managed_evidence import (
    STACK_ASSERTIONS,
    collect_managed_stack_evidence,
    validate_managed_stack_receipt,
    verify_agent_memory_round_trip,
    verify_public_demo,
    write_managed_stack_receipt,
)
from continuity_ledger.lambda_handler import make_handler
from continuity_ledger.service import ContinuityService
from continuity_ledger.store import SQLiteLedgerStore


class FakeMCPClient:
    async def inspect(
        self,
        tool_name: str,
        arguments: dict[str, object] | None = None,
        *,
        verified_at: datetime | None = None,
    ) -> dict[str, object]:
        if tool_name != "list_databases" or arguments != {}:
            raise AssertionError("unexpected MCP request")
        when = verified_at or datetime.now(timezone.utc)
        return {
            "schema_version": "1.0",
            "verified_at": when.replace(microsecond=0).isoformat(),
            "scope": "authorized CockroachDB Cloud managed MCP read-only tool call",
            "managed_mcp_claimed": True,
            "single_cluster_scoped": True,
            "tool": "list_databases",
            "advertised_read_only_tools": ["list_databases"],
            "content_block_count": 1,
            "tool_result_sha256": "a" * 64,
            "raw_result_published": False,
        }


def successful_demo_request(
    method: str,
    url: str,
    body: dict[str, object] | None,
) -> tuple[int, dict[str, str], bytes]:
    route = "/" + url.split("/", 3)[-1] if url.count("/") >= 3 else "/"
    if route == "/healthz" and method == "GET":
        payload = {"status": "ok", "mode": "synthetic-only"}
    elif route == "/" and method == "GET":
        return 200, {"content-type": "text/html"}, b"<h1>Continuity Ledger</h1>"
    elif route == "/demo/scenarios" and method == "GET":
        payload = {"scenarios": [{"id": "ingest_backlog"}]}
    elif route == "/demo/seed" and method == "POST":
        payload = {"memory": {"inserted": 3, "available": 3}}
    elif route == "/demo/run" and method == "POST":
        if body != {"scenario_id": "ingest_backlog"}:
            raise AssertionError("unexpected demo scenario")
        payload = {
            "action": "inspect_ingest_validation",
            "citations": ["prior_ingest:1"],
            "decision_persisted": True,
        }
    elif route == "/agent/run" and method == "POST":
        return 401, {"content-type": "application/json"}, b'{"error":"identity required"}'
    else:
        raise AssertionError(f"unexpected request: {method} {route}")
    return 200, {"content-type": "application/json"}, json.dumps(payload).encode()


class ManagedEvidenceTests(unittest.IsolatedAsyncioTestCase):
    def test_agent_round_trip_retrieves_cites_acts_and_persists(self) -> None:
        service = ContinuityService(SQLiteLedgerStore(":memory:"))
        evidence = verify_agent_memory_round_trip(service)
        self.assertEqual(evidence["action"], "inspect_ingest_validation")
        self.assertGreaterEqual(evidence["citation_count"], 1)
        self.assertTrue(all(evidence["assertions"].values()))

    def test_public_demo_verifier_hashes_origin_and_requires_all_contracts(self) -> None:
        evidence = verify_public_demo(
            "https://synthetic-demo.example",
            request=successful_demo_request,
        )
        self.assertRegex(evidence["origin_sha256"], r"^[0-9a-f]{64}$")
        self.assertNotIn("synthetic-demo.example", json.dumps(evidence))
        self.assertTrue(all(evidence["assertions"].values()))

    def test_public_demo_verifier_rejects_http_or_failed_action(self) -> None:
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            verify_public_demo(
                "http://synthetic-demo.example",
                request=successful_demo_request,
            )

        def wrong_action(
            method: str,
            url: str,
            body: dict[str, object] | None,
        ) -> tuple[int, dict[str, str], bytes]:
            status, headers, payload = successful_demo_request(method, url, body)
            if url.endswith("/demo/run"):
                payload = b'{"action":"request_more_evidence","citations":[],"decision_persisted":false}'
            return status, headers, payload

        with self.assertRaisesRegex(RuntimeError, "demo_agent_run_succeeded"):
            verify_public_demo(
                "https://synthetic-demo.example",
                request=wrong_action,
            )

    async def test_combined_receipt_is_complete_canonical_and_secret_free(self) -> None:
        service = ContinuityService(SQLiteLedgerStore(":memory:"))
        receipt = await collect_managed_stack_evidence(
            lambda: object(),
            FakeMCPClient(),
            "https://synthetic-demo.example",
            service=service,
            bootstrapper=lambda _factory: dict.fromkeys(REQUIRED_ASSERTIONS, True),
            request=successful_demo_request,
            verified_at=datetime(2026, 8, 11, 20, 0, tzinfo=timezone.utc),
        )
        validate_managed_stack_receipt(receipt)
        self.assertEqual(set(receipt["assertions"]), set(STACK_ASSERTIONS))
        self.assertTrue(all(receipt["assertions"].values()))
        serialized = json.dumps(receipt, sort_keys=True)
        for forbidden in (
            "synthetic-demo.example",
            "postgresql://",
            "database_url",
            "password",
            "authorization",
            "cluster_id",
        ):
            self.assertNotIn(forbidden, serialized.casefold())

        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "managed-stack.json"
            digest = write_managed_stack_receipt(destination, receipt)
            reopened = json.loads(destination.read_text(encoding="utf-8"))
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
            self.assertEqual(reopened, receipt)
            self.assertFalse(destination.with_suffix(".json.tmp").exists())

    async def test_combined_verifier_handles_shared_idempotent_managed_store(self) -> None:
        service = ContinuityService(SQLiteLedgerStore(":memory:"))
        handler = make_handler(lambda: service)

        def shared_store_request(
            method: str,
            url: str,
            body: dict[str, object] | None,
        ) -> tuple[int, dict[str, str], bytes]:
            route = "/" + url.split("/", 3)[-1] if url.count("/") >= 3 else "/"
            event = {
                "rawPath": route,
                "requestContext": {"http": {"method": method}},
                "body": json.dumps(body or {}),
            }
            response = handler(event, None)
            return (
                int(response["statusCode"]),
                dict(response["headers"]),
                str(response["body"]).encode("utf-8"),
            )

        receipt = await collect_managed_stack_evidence(
            lambda: object(),
            FakeMCPClient(),
            "https://synthetic-demo.example",
            service=service,
            bootstrapper=lambda _factory: dict.fromkeys(REQUIRED_ASSERTIONS, True),
            request=shared_store_request,
        )
        self.assertTrue(all(receipt["assertions"].values()))
        self.assertEqual(
            receipt["components"]["agent"]["action"],
            "inspect_ingest_validation",
        )

    async def test_no_combined_receipt_is_written_for_incomplete_evidence(self) -> None:
        def failed_demo(
            method: str,
            url: str,
            body: dict[str, object] | None,
        ) -> tuple[int, dict[str, str], bytes]:
            if url.endswith("/healthz"):
                return 503, {}, b'{"status":"down"}'
            return successful_demo_request(method, url, body)

        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "managed-stack.json"
            with self.assertRaisesRegex(RuntimeError, "demo_health_public"):
                receipt = await collect_managed_stack_evidence(
                    lambda: object(),
                    FakeMCPClient(),
                    "https://synthetic-demo.example",
                    service=ContinuityService(SQLiteLedgerStore(":memory:")),
                    bootstrapper=lambda _factory: dict.fromkeys(
                        REQUIRED_ASSERTIONS, True
                    ),
                    request=failed_demo,
                )
                write_managed_stack_receipt(destination, receipt)
            self.assertFalse(destination.exists())

    def test_receipt_rejects_private_material(self) -> None:
        invalid = {
            "managed_cloud_claimed": True,
            "assertions": dict.fromkeys(STACK_ASSERTIONS, True),
            "components": {
                "schema": {},
                "agent": {},
                "mcp": {},
                "demo": {"origin_sha256": "b" * 64},
            },
            "password": "never-publish",
        }
        with self.assertRaises(ValueError):
            validate_managed_stack_receipt(invalid)


if __name__ == "__main__":
    unittest.main()
