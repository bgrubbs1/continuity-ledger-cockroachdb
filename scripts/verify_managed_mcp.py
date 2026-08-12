#!/usr/bin/env python3
"""Run one authorized, read-only CockroachDB Cloud MCP inspection."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

from continuity_ledger.mcp import (
    ManagedMCPClient,
    ManagedMCPConfig,
    write_mcp_receipt,
)


async def _run(args: argparse.Namespace) -> tuple[Path, str]:
    config = ManagedMCPConfig.from_environment()
    arguments = json.loads(args.arguments_json)
    if not isinstance(arguments, dict):
        raise ValueError("--arguments-json must decode to a JSON object")
    receipt = await ManagedMCPClient(config).inspect(args.tool, arguments)
    digest = write_mcp_receipt(args.receipt, receipt)
    return args.receipt, digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", default="list_databases")
    parser.add_argument("--arguments-json", default="{}")
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path("artifacts/public/managed-mcp-readonly.json"),
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
