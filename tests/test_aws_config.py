from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from continuity_ledger.aws_config import resolve_database_url
from scripts.put_aws_database_parameter import put_parameter


class FakeSSM:
    def __init__(self, value: str = "postgresql://managed-value") -> None:
        self.value = value
        self.get_calls: list[dict[str, object]] = []
        self.put_calls: list[dict[str, object]] = []

    def get_parameter(self, **kwargs: object) -> dict[str, object]:
        self.get_calls.append(kwargs)
        return {"Parameter": {"Value": self.value}}

    def put_parameter(self, **kwargs: object) -> dict[str, object]:
        self.put_calls.append(kwargs)
        return {"Version": 3}


class AWSConfigTests(unittest.TestCase):
    def tearDown(self) -> None:
        resolve_database_url.cache_clear()

    def test_managed_runtime_decrypts_only_named_parameter(self) -> None:
        client = FakeSSM()
        with patch.dict(
            os.environ,
            {"DATABASE_PARAMETER_NAME": "/continuity-ledger/database-url"},
            clear=True,
        ):
            value = resolve_database_url(lambda service: client)
        self.assertEqual(value, "postgresql://managed-value")
        self.assertEqual(
            client.get_calls,
            [{"Name": "/continuity-ledger/database-url", "WithDecryption": True}],
        )

    def test_local_database_url_does_not_contact_aws(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://local"}, clear=True):
            value = resolve_database_url(lambda _service: self.fail("AWS must not be called"))
        self.assertEqual(value, "postgresql://local")

    def test_parameter_writer_uses_secure_standard_tier_and_safe_receipt(self) -> None:
        client = FakeSSM()
        receipt = put_parameter(
            client,
            "/continuity-ledger/database-url",
            "postgresql://super-secret",
        )
        self.assertEqual(client.put_calls[0]["Type"], "SecureString")
        self.assertEqual(client.put_calls[0]["Tier"], "Standard")
        self.assertTrue(client.put_calls[0]["Overwrite"])
        serialized = json.dumps(receipt)
        self.assertNotIn("super-secret", serialized)
        self.assertNotIn("/continuity-ledger/database-url", serialized)

    def test_parameter_writer_rejects_relative_name_and_empty_value(self) -> None:
        with self.assertRaises(ValueError):
            put_parameter(FakeSSM(), "relative", "postgresql://value")
        with self.assertRaises(ValueError):
            put_parameter(FakeSSM(), "/absolute", "")


if __name__ == "__main__":
    unittest.main()
