#!/usr/bin/env python3
"""Bootstrap and verify the schema in an authorized CockroachDB Cloud cluster."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from continuity_ledger.cockroach import psycopg_connection_factory
from continuity_ledger.managed_bootstrap import (
    bootstrap_managed_schema,
    build_managed_schema_receipt,
    write_managed_schema_receipt,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path("artifacts/private/managed-schema-bootstrap.json"),
        help="Secret-free receipt destination (DATABASE_URL is never written).",
    )
    args = parser.parse_args(argv)

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        parser.error("DATABASE_URL environment variable is required")

    try:
        assertions = bootstrap_managed_schema(
            psycopg_connection_factory(database_url)
        )
        receipt = build_managed_schema_receipt(assertions)
        digest = write_managed_schema_receipt(args.receipt, receipt)
    except Exception as exc:
        # Never echo a driver message: it may contain a cluster endpoint or
        # connection detail. The exception class is enough for local triage.
        print(
            json.dumps(
                {"status": "failed", "error_type": type(exc).__name__},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "status": "verified",
                "receipt_file": args.receipt.name,
                "sha256": digest,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
