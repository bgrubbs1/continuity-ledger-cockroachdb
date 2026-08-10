from __future__ import annotations

import unittest

from scripts.verify_local_cockroach import build_receipt, validate_receipt


class LocalCockroachVerifierTests(unittest.TestCase):
    def test_receipt_is_minimal_and_secret_free(self) -> None:
        receipt = build_receipt(
            image_reference="cockroachdb/cockroach:v26.2.3",
            image_digest="sha256:" + ("a" * 64),
            assertions={
                "schema_initialized": True,
                "vector_index_present": True,
                "idempotent_replay_blocked": True,
                "sequence_conflict_blocked": True,
                "tenant_isolation_preserved": True,
                "similarity_result_verified": True,
                "serialization_retry_verified": True,
            },
        )

        validate_receipt(receipt)
        self.assertEqual(receipt["schema_version"], "1.0")
        self.assertEqual(receipt["data_boundary"], "deliberately fictional events only")
        self.assertNotIn("connection", receipt)
        self.assertNotIn("host", receipt)
        self.assertNotIn("port", receipt)

    def test_receipt_rejects_connection_material(self) -> None:
        receipt = build_receipt(
            image_reference="cockroachdb/cockroach:v26.2.3",
            image_digest="sha256:" + ("b" * 64),
            assertions={"schema_initialized": True},
        )
        receipt["connection"] = "postgresql://root@127.0.0.1:26257/defaultdb"

        with self.assertRaises(ValueError):
            validate_receipt(receipt)

    def test_receipt_requires_every_assertion_to_pass(self) -> None:
        receipt = build_receipt(
            image_reference="cockroachdb/cockroach:v26.2.3",
            image_digest="sha256:" + ("c" * 64),
            assertions={"tenant_isolation_preserved": False},
        )

        with self.assertRaises(ValueError):
            validate_receipt(receipt)


if __name__ == "__main__":
    unittest.main()
