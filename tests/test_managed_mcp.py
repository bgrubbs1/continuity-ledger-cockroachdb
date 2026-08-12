from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from continuity_ledger.mcp import (
    ManagedMCPClient,
    ManagedMCPConfig,
    validate_mcp_receipt,
    write_mcp_receipt,
)


CLUSTER_ID = "f98e5aba-7da3-4e73-b201-51111c421549"


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def list_tools(self) -> object:
        return SimpleNamespace(
            tools=[
                SimpleNamespace(name="list_databases"),
                SimpleNamespace(name="get_table_schema"),
                SimpleNamespace(name="insert_rows"),
            ]
        )

    async def call_tool(self, name: str, arguments: dict[str, object]) -> object:
        self.calls.append((name, arguments))
        return SimpleNamespace(isError=False, content=[{"synthetic": "schema"}])


class ManagedMCPTests(unittest.IsolatedAsyncioTestCase):
    def test_environment_config_is_https_cluster_scoped_and_secret_safe(self) -> None:
        environment = {
            "COCKROACH_MCP_URL": "https://cockroachlabs.cloud/mcp",
            "COCKROACH_MCP_TOKEN": "super-secret",
            "COCKROACH_CLUSTER_ID": CLUSTER_ID,
        }
        with patch.dict("os.environ", environment, clear=True):
            config = ManagedMCPConfig.from_environment()
        self.assertEqual(config.request_headers()["mcp-cluster-id"], CLUSTER_ID)
        self.assertEqual(
            config.request_headers()["Authorization"],
            "Bearer super-secret",
        )
        self.assertNotIn("super-secret", json.dumps(config.safe_summary()))
        self.assertNotIn(CLUSTER_ID, json.dumps(config.safe_summary()))

    def test_environment_config_rejects_invalid_cluster_scope(self) -> None:
        environment = {
            "COCKROACH_MCP_URL": "https://cockroachlabs.cloud/mcp",
            "COCKROACH_MCP_TOKEN": "token",
            "COCKROACH_CLUSTER_ID": "not-a-cluster-id",
        }
        with patch.dict("os.environ", environment, clear=True):
            with self.assertRaises(ValueError):
                ManagedMCPConfig.from_environment()

    async def test_client_discovers_and_calls_only_read_only_tool(self) -> None:
        session = FakeSession()

        @asynccontextmanager
        async def session_factory(_config: ManagedMCPConfig):
            yield session

        config = ManagedMCPConfig(
            "https://cockroachlabs.cloud/mcp",
            "super-secret",
            CLUSTER_ID,
        )
        receipt = await ManagedMCPClient(
            config,
            session_factory=session_factory,
        ).inspect(
            "list_databases",
            {},
            verified_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        )
        self.assertEqual(session.calls, [("list_databases", {})])
        self.assertEqual(receipt["tool"], "list_databases")
        self.assertEqual(
            receipt["advertised_read_only_tools"],
            ["get_table_schema", "list_databases"],
        )
        serialized = json.dumps(receipt)
        self.assertNotIn("super-secret", serialized)
        self.assertNotIn(CLUSTER_ID, serialized)

    async def test_client_rejects_write_tool_before_opening_session(self) -> None:
        opened = False

        @asynccontextmanager
        async def session_factory(_config: ManagedMCPConfig):
            nonlocal opened
            opened = True
            yield FakeSession()

        client = ManagedMCPClient(
            ManagedMCPConfig(
                "https://cockroachlabs.cloud/mcp",
                "super-secret",
                CLUSTER_ID,
            ),
            session_factory=session_factory,
        )
        with self.assertRaises(ValueError):
            await client.inspect("insert_rows", {})
        self.assertFalse(opened)

    async def test_receipt_round_trip_is_canonical_and_secret_free(self) -> None:
        session = FakeSession()

        @asynccontextmanager
        async def session_factory(_config: ManagedMCPConfig):
            yield session

        receipt = await ManagedMCPClient(
            ManagedMCPConfig(
                "https://cockroachlabs.cloud/mcp",
                "super-secret",
                CLUSTER_ID,
            ),
            session_factory=session_factory,
        ).inspect(
            "get_table_schema",
            {"database": "defaultdb", "table": "ledger_events"},
            verified_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "receipt.json"
            digest = write_mcp_receipt(destination, receipt)
            reopened = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(len(digest), 64)
        validate_mcp_receipt(reopened)
        self.assertNotIn("super-secret", json.dumps(reopened))

    def test_receipt_rejects_private_or_write_material(self) -> None:
        base = {
            "managed_mcp_claimed": True,
            "single_cluster_scoped": True,
            "tool": "list_databases",
            "tool_result_sha256": "a" * 64,
        }
        validate_mcp_receipt(base)
        with self.assertRaises(ValueError):
            validate_mcp_receipt({**base, "authorization": "Bearer secret"})
        with self.assertRaises(ValueError):
            validate_mcp_receipt({**base, "tool": "insert_rows"})


if __name__ == "__main__":
    unittest.main()
