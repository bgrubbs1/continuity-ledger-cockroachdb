from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from continuity_ledger.managed_bootstrap import (
    REQUIRED_ASSERTIONS,
    bootstrap_managed_schema,
    build_managed_schema_receipt,
    validate_managed_schema_receipt,
    write_managed_schema_receipt,
)


class FakeCursor:
    def __init__(self, queries: list[str]) -> None:
        self.queries = queries
        self.current = ""

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str) -> None:
        self.current = query
        self.queries.append(query)

    def fetchone(self) -> tuple[str] | None:
        if "information_schema.tables" in self.current:
            return ("ledger_events",)
        if "SHOW INDEXES FROM ledger_events" in self.current:
            return ("ledger_events_embedding_idx",)
        return None


class FakeConnection:
    def __init__(self, queries: list[str]) -> None:
        self.queries = queries
        self.commits = 0
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.queries)

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed = True


class ManagedBootstrapTests(unittest.TestCase):
    def test_bootstrap_is_idempotent_and_verifies_table_and_vector_index(self) -> None:
        queries: list[str] = []
        connections: list[FakeConnection] = []

        def factory() -> FakeConnection:
            connection = FakeConnection(queries)
            connections.append(connection)
            return connection

        first = bootstrap_managed_schema(factory)
        second = bootstrap_managed_schema(factory)

        self.assertEqual(first, dict.fromkeys(REQUIRED_ASSERTIONS, True))
        self.assertEqual(second, first)
        self.assertEqual(len(connections), 4)
        self.assertTrue(all(connection.closed for connection in connections))
        self.assertEqual(sum("CREATE TABLE IF NOT EXISTS" in query for query in queries), 2)
        self.assertEqual(sum("CREATE VECTOR INDEX IF NOT EXISTS" in query for query in queries), 2)
        self.assertEqual(sum("information_schema.tables" in query for query in queries), 2)
        self.assertEqual(sum("SHOW INDEXES FROM ledger_events" in query for query in queries), 2)

    def test_receipt_is_secret_free_and_records_only_verified_schema(self) -> None:
        receipt = build_managed_schema_receipt(
            dict.fromkeys(REQUIRED_ASSERTIONS, True),
            verified_at=datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc),
        )
        validate_managed_schema_receipt(receipt)
        payload = json.dumps(receipt, sort_keys=True)
        for forbidden in (
            "postgresql://",
            "database_url",
            "password",
            "token",
            "hostname",
            "C:\\Users\\",
        ):
            self.assertNotIn(forbidden.casefold(), payload.casefold())
        self.assertTrue(receipt["managed_cloud_claimed"])
        self.assertEqual(set(receipt["assertions"]), set(REQUIRED_ASSERTIONS))

    def test_receipt_rejects_failed_or_private_material(self) -> None:
        assertions = dict.fromkeys(REQUIRED_ASSERTIONS, True)
        assertions[REQUIRED_ASSERTIONS[0]] = False
        with self.assertRaisesRegex(ValueError, "fully passing"):
            build_managed_schema_receipt(assertions)

        receipt = build_managed_schema_receipt(dict.fromkeys(REQUIRED_ASSERTIONS, True))
        receipt["connection_url"] = "postgresql://private.invalid/ledger"
        with self.assertRaisesRegex(ValueError, "prohibited"):
            validate_managed_schema_receipt(receipt)

    def test_written_receipt_is_reopened_validated_and_hashed(self) -> None:
        receipt = build_managed_schema_receipt(dict.fromkeys(REQUIRED_ASSERTIONS, True))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "managed-schema.json"
            digest = write_managed_schema_receipt(path, receipt)
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
            reopened = json.loads(path.read_text(encoding="utf-8"))
            validate_managed_schema_receipt(reopened)
            self.assertEqual(reopened, receipt)


if __name__ == "__main__":
    unittest.main()
