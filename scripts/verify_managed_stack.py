#!/usr/bin/env python3
"""Verify the authorized managed stack and write one secret-free receipt."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

from continuity_ledger.cockroach import psycopg_connection_factory
from continuity_ledger.managed_evidence import (
    collect_managed_stack_evidence,
    write_managed_stack_receipt,
)
from continuity_ledger.mcp import ManagedMCPClient, ManagedMCPConfig


async def _run(args: argparse.Namespace) -> tuple[Path, str]:
    database_url = os.environ.get("DATABASE_URL", "")
    demo_origin = os.environ.get("CONTINUITY_DEMO_URL", "")
    if not database_url:
        raise ValueError("DATABASE_URL is required")
    if not demo_origin:
        raise ValueError("CONTINUITY_DEMO_URL is required")
    receipt = await collect_managed_stack_evidence(
        psycopg_connection_factory(database_url),
        ManagedMCPClient(ManagedMCPConfig.from_environment()),
        demo_origin,
    )
    digest = write_managed_stack_receipt(args.receipt, receipt)
    return args.receipt, digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path("artifacts/private/managed-stack-evidence.json"),
    )
    args = parser.parse_args(argv)
    try:
        receipt, digest = asyncio.run(_run(args))
    except Exception as exc:
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
            {"status": "verified", "receipt_file": receipt.name, "sha256": digest},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
