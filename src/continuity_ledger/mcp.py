"""Read-only client boundary for the official CockroachDB managed MCP endpoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from typing import Any, AsyncContextManager, Callable, Mapping
from urllib.parse import urlparse
from uuid import UUID


READ_ONLY_TOOLS = frozenset(
    {
        "list_clusters",
        "get_cluster",
        "list_databases",
        "list_tables",
        "get_table_schema",
        "select_query",
        "explain_query",
        "show_running_queries",
    }
)

_BANNED_RECEIPT_KEYS = re.compile(
    r"(?:authorization|token|secret|password|cluster_id|connection|dsn|host)", re.I
)


@dataclass(frozen=True, slots=True)
class ManagedMCPConfig:
    url: str
    token: str
    cluster_id: str
    read_only: bool = True

    @classmethod
    def from_environment(cls) -> "ManagedMCPConfig":
        url = os.environ.get("COCKROACH_MCP_URL", "https://cockroachlabs.cloud/mcp")
        token = os.environ.get("COCKROACH_MCP_TOKEN", "")
        cluster_id = os.environ.get("COCKROACH_CLUSTER_ID", "")
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("CockroachDB MCP URL must be HTTPS")
        if not token:
            raise ValueError("COCKROACH_MCP_TOKEN is required for an authorized call")
        try:
            UUID(cluster_id)
        except (ValueError, AttributeError) as exc:
            raise ValueError("COCKROACH_CLUSTER_ID must be a UUID") from exc
        return cls(url=url, token=token, cluster_id=cluster_id)

    def request_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "mcp-cluster-id": self.cluster_id,
        }

    def safe_summary(self) -> dict[str, object]:
        return {
            "url": self.url,
            "read_only": self.read_only,
            "authenticated": bool(self.token),
            "single_cluster_scoped": bool(self.cluster_id),
        }


SessionFactory = Callable[[ManagedMCPConfig], AsyncContextManager[Any]]


@asynccontextmanager
async def _official_session(config: ManagedMCPConfig):
    """Open an initialized Streamable HTTP MCP session.

    Imports stay inside this cloud-only boundary so credential-free unit tests
    and the local reference service do not require the MCP package.
    """

    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    import httpx

    async with httpx.AsyncClient(
        headers=config.request_headers(),
        follow_redirects=True,
        timeout=30,
    ) as http_client:
        async with streamable_http_client(
            config.url,
            http_client=http_client,
        ) as (read_stream, write_stream, _get_session_id):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session


class ManagedMCPClient:
    """Discover and invoke only CockroachDB's documented read-only tools."""

    def __init__(
        self,
        config: ManagedMCPConfig,
        *,
        session_factory: SessionFactory = _official_session,
    ) -> None:
        if not config.read_only:
            raise ValueError("Continuity Ledger MCP integration is read-only")
        self._config = config
        self._session_factory = session_factory

    async def inspect(
        self,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        verified_at: datetime | None = None,
    ) -> dict[str, Any]:
        if tool_name not in READ_ONLY_TOOLS:
            raise ValueError(f"MCP tool is not allowed by the read-only policy: {tool_name}")

        async with self._session_factory(self._config) as session:
            listed = await session.list_tools()
            advertised = sorted(
                tool.name
                for tool in listed.tools
                if tool.name in READ_ONLY_TOOLS
            )
            if tool_name not in advertised:
                raise RuntimeError(f"managed MCP did not advertise required tool: {tool_name}")
            result = await session.call_tool(tool_name, dict(arguments or {}))

        if bool(getattr(result, "isError", False)):
            raise RuntimeError(f"managed MCP read-only tool failed: {tool_name}")
        content = getattr(result, "content", ())
        result_fingerprint = hashlib.sha256(
            repr(content).encode("utf-8", errors="replace")
        ).hexdigest()
        when = verified_at or datetime.now(timezone.utc)
        receipt: dict[str, Any] = {
            "schema_version": "1.0",
            "verified_at": when.astimezone(timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
            "scope": "authorized CockroachDB Cloud managed MCP read-only tool call",
            "managed_mcp_claimed": True,
            "single_cluster_scoped": True,
            "tool": tool_name,
            "advertised_read_only_tools": advertised,
            "content_block_count": len(content),
            "tool_result_sha256": result_fingerprint,
            "raw_result_published": False,
        }
        validate_mcp_receipt(receipt)
        return receipt


def validate_mcp_receipt(receipt: Mapping[str, Any]) -> None:
    if receipt.get("managed_mcp_claimed") is not True:
        raise ValueError("MCP receipt must explicitly identify its evidence scope")
    if receipt.get("single_cluster_scoped") is not True:
        raise ValueError("MCP receipt requires single-cluster scoping")
    if receipt.get("tool") not in READ_ONLY_TOOLS:
        raise ValueError("MCP receipt contains a non-read-only tool")
    if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("tool_result_sha256", ""))):
        raise ValueError("MCP receipt requires a result SHA-256")

    def inspect(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if _BANNED_RECEIPT_KEYS.search(str(key)):
                    raise ValueError(f"MCP receipt contains prohibited key: {key}")
                inspect(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                inspect(child)
        elif isinstance(value, str):
            if "Bearer " in value or "postgresql://" in value:
                raise ValueError("MCP receipt contains private connection material")

    inspect(receipt)


def write_mcp_receipt(path: os.PathLike[str] | str, receipt: Mapping[str, Any]) -> str:
    from pathlib import Path

    validate_mcp_receipt(receipt)
    destination = Path(path)
    payload = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    validate_mcp_receipt(json.loads(destination.read_text(encoding="utf-8")))
    return hashlib.sha256(payload).hexdigest()
