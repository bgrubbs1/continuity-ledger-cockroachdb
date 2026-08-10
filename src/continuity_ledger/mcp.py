"""Fail-closed configuration for the official CockroachDB managed MCP endpoint."""

from __future__ import annotations

from dataclasses import dataclass
import os
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class ManagedMCPConfig:
    url: str
    token: str
    read_only: bool = True

    @classmethod
    def from_environment(cls) -> "ManagedMCPConfig":
        url = os.environ.get("COCKROACH_MCP_URL", "https://cockroachlabs.cloud/mcp")
        token = os.environ.get("COCKROACH_MCP_TOKEN", "")
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("CockroachDB MCP URL must be HTTPS")
        if not token:
            raise ValueError("COCKROACH_MCP_TOKEN is required for an authorized call")
        return cls(url=url, token=token)

    def authorization_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def safe_summary(self) -> dict[str, object]:
        return {"url": self.url, "read_only": self.read_only, "authenticated": bool(self.token)}

