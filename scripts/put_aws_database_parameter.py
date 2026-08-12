#!/usr/bin/env python3
"""Store DATABASE_URL in an encrypted AWS SSM Standard parameter."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys


def build_receipt(name: str, version: int) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "scope": "AWS Systems Manager encrypted Standard parameter",
        "service": "AWS Systems Manager Parameter Store",
        "parameter_name_sha256": hashlib.sha256(name.encode("utf-8")).hexdigest(),
        "parameter_type": "SecureString",
        "parameter_tier": "Standard",
        "version": version,
        "database_value_published": False,
    }


def put_parameter(client: object, name: str, value: str) -> dict[str, object]:
    if not name.startswith("/"):
        raise ValueError("parameter name must start with /")
    if not value:
        raise ValueError("DATABASE_URL is required")
    response = client.put_parameter(
        Name=name,
        Description="Synthetic-only Continuity Ledger contest database URL",
        Value=value,
        Type="SecureString",
        Overwrite=True,
        Tier="Standard",
    )
    return build_receipt(name, int(response["Version"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="/continuity-ledger/database-url")
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path("artifacts/public/aws-parameter-store.json"),
    )
    args = parser.parse_args(argv)
    database_url = os.environ.get("DATABASE_URL", "")
    try:
        import boto3

        receipt = put_parameter(boto3.client("ssm"), args.name, database_url)
        payload = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
    except Exception as exc:
        print(
            json.dumps({"status": "failed", "error_type": type(exc).__name__}, sort_keys=True),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {"status": "stored", "receipt_file": args.receipt.name, "sha256": digest},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
