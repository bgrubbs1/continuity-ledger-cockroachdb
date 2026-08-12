"""Fail-closed evidence collection for an authorized managed deployment."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Awaitable, Callable, Mapping, Protocol
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .cockroach import CockroachLedgerStore
from .demo import DEMO_TENANT, SCENARIOS, run_demo_scenario, seed_demo_memory
from .managed_bootstrap import (
    bootstrap_managed_schema,
    build_managed_schema_receipt,
    validate_managed_schema_receipt,
)
from .mcp import validate_mcp_receipt
from .service import ContinuityService


STACK_ASSERTIONS = (
    "schema_verified",
    "agent_recalled_memory",
    "agent_cited_memory",
    "agent_action_matched_contract",
    "agent_observation_persisted",
    "agent_decision_persisted",
    "managed_mcp_read_only_call_verified",
    "demo_health_public",
    "demo_ui_public",
    "demo_catalog_public",
    "demo_seed_succeeded",
    "demo_agent_run_succeeded",
    "protected_agent_route_rejected_anonymous_request",
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BANNED_KEYS = re.compile(
    r"(?:authorization|token|secret|password|database_url|dsn|host|cluster_id|connection|path)",
    re.I,
)
_BANNED_VALUES = (
    re.compile(r"postgres(?:ql)?://", re.I),
    re.compile(r"Bearer\s+", re.I),
    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    re.compile(r"[A-Z]:\\", re.I),
    re.compile(r"https?://", re.I),
)


class MCPInspector(Protocol):
    async def inspect(
        self,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        verified_at: datetime | None = None,
    ) -> dict[str, Any]: ...


HTTPResponse = tuple[int, Mapping[str, str], bytes]
HTTPRequest = Callable[[str, str, Mapping[str, Any] | None], HTTPResponse]
Bootstrapper = Callable[[Callable[[], object]], Mapping[str, bool]]


def verify_agent_memory_round_trip(
    service: ContinuityService,
    *,
    scenario_id: str = "ingest_backlog",
) -> dict[str, Any]:
    """Exercise retrieve-decide-cite-record against the configured store."""

    scenario = SCENARIOS.get(scenario_id)
    if scenario is None:
        raise ValueError("unknown managed evidence scenario")

    seed = seed_demo_memory(service)
    outcome = run_demo_scenario(service, scenario_id)
    if outcome is None:
        raise RuntimeError("managed memory was not retrievable after seeding")

    persisted = service.recall(DEMO_TENANT, scenario.observation, 20)
    observation_present = any(
        item.event.incident_id == scenario.run_incident_id
        and item.event.kind == "observation"
        for item in persisted
    )
    decision_present = any(
        item.event.incident_id == scenario.run_incident_id
        and item.event.kind == "decision"
        for item in persisted
    )
    assertions = {
        "agent_recalled_memory": outcome.recalled_count >= 1,
        "agent_cited_memory": bool(outcome.citations),
        "agent_action_matched_contract": outcome.action == scenario.expected_action,
        "agent_observation_persisted": observation_present,
        "agent_decision_persisted": decision_present,
    }
    if not all(assertions.values()):
        failed = sorted(name for name, passed in assertions.items() if not passed)
        raise RuntimeError("managed agent evidence failed: " + ", ".join(failed))

    return {
        "scenario": scenario_id,
        "seed_records_available": int(seed["available"]),
        "action": outcome.action,
        "citation_count": len(outcome.citations),
        "recalled_count": outcome.recalled_count,
        "assertions": assertions,
    }


def _urllib_request(
    method: str,
    url: str,
    body: Mapping[str, Any] | None,
) -> HTTPResponse:
    payload = None
    headers = {"accept": "application/json, text/html"}
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        headers["content-type"] = "application/json"
    request = Request(url, data=payload, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310 - caller enforces HTTPS.
            return int(response.status), dict(response.headers.items()), response.read()
    except HTTPError as exc:
        return int(exc.code), dict(exc.headers.items()), exc.read()


def verify_public_demo(
    demo_origin: str,
    *,
    request: HTTPRequest = _urllib_request,
    scenario_id: str = "ingest_backlog",
) -> dict[str, Any]:
    """Verify the logged-out AWS demo without retaining its origin or payloads."""

    parsed = urlparse(demo_origin)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("managed demo origin must be a plain HTTPS origin")
    origin = demo_origin.rstrip("/")

    def call(method: str, route: str, body: Mapping[str, Any] | None = None) -> tuple[int, bytes]:
        status, _headers, payload = request(method, origin + route, body)
        return status, payload

    health_status, health_payload = call("GET", "/healthz")
    ui_status, ui_payload = call("GET", "/")
    catalog_status, catalog_payload = call("GET", "/demo/scenarios")
    seed_status, seed_payload = call("POST", "/demo/seed", {})
    run_status, run_payload = call("POST", "/demo/run", {"scenario_id": scenario_id})
    protected_status, _protected_payload = call("POST", "/agent/run", {})

    health = _json_object(health_payload, "health")
    catalog = _json_object(catalog_payload, "catalog")
    seed = _json_object(seed_payload, "seed")
    run = _json_object(run_payload, "run")
    scenario = SCENARIOS[scenario_id]
    scenario_ids = {
        item.get("id")
        for item in catalog.get("scenarios", [])
        if isinstance(item, Mapping)
    }
    memory = seed.get("memory") if isinstance(seed.get("memory"), Mapping) else {}
    assertions = {
        "demo_health_public": health_status == 200 and health.get("status") == "ok",
        "demo_ui_public": ui_status == 200 and b"Continuity Ledger" in ui_payload,
        "demo_catalog_public": catalog_status == 200 and scenario_id in scenario_ids,
        "demo_seed_succeeded": seed_status == 200
        and int(memory.get("available", 0)) == len(SCENARIOS),
        "demo_agent_run_succeeded": run_status == 200
        and run.get("action") == scenario.expected_action
        and bool(run.get("citations"))
        and run.get("decision_persisted") is True,
        "protected_agent_route_rejected_anonymous_request": protected_status in {401, 403},
    }
    if not all(assertions.values()):
        failed = sorted(name for name, passed in assertions.items() if not passed)
        raise RuntimeError("managed demo evidence failed: " + ", ".join(failed))

    return {
        "origin_sha256": hashlib.sha256(origin.encode("utf-8")).hexdigest(),
        "scenario": scenario_id,
        "assertions": assertions,
    }


def _json_object(payload: bytes, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"managed demo returned invalid {label} JSON") from exc
    if not isinstance(value, Mapping):
        raise RuntimeError(f"managed demo returned non-object {label} JSON")
    return value


async def collect_managed_stack_evidence(
    connection_factory: Callable[[], object],
    mcp_client: MCPInspector,
    demo_origin: str,
    *,
    service: ContinuityService | None = None,
    bootstrapper: Bootstrapper = bootstrap_managed_schema,
    request: HTTPRequest = _urllib_request,
    verified_at: datetime | None = None,
) -> dict[str, Any]:
    """Collect one all-or-nothing receipt across CockroachDB, MCP, and AWS."""

    when = (verified_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    schema = build_managed_schema_receipt(
        bootstrapper(connection_factory),
        verified_at=when,
    )
    # Exercise the public endpoint before the direct store proof. Both use the
    # same fixed idempotency keys in a real deployment; this ordering proves the
    # hosted write first and then verifies those records directly without
    # misclassifying a safe replay as a failed write.
    demo = verify_public_demo(demo_origin, request=request)
    managed_service = service or ContinuityService(CockroachLedgerStore(connection_factory))
    agent = verify_agent_memory_round_trip(managed_service)
    mcp = await mcp_client.inspect("list_databases", {}, verified_at=when)
    validate_mcp_receipt(mcp)

    assertions = {"schema_verified": True, **agent["assertions"]}
    assertions["managed_mcp_read_only_call_verified"] = True
    assertions.update(demo["assertions"])
    if set(assertions) != set(STACK_ASSERTIONS) or not all(assertions.values()):
        raise RuntimeError("managed stack evidence is incomplete")

    receipt: dict[str, Any] = {
        "schema_version": "1.0",
        "verified_at": when.replace(microsecond=0).isoformat(),
        "scope": "authorized end-to-end CockroachDB and AWS managed verification",
        "managed_cloud_claimed": True,
        "data_boundary": "fixed fictional contest scenarios only",
        "components": {
            "schema": schema,
            "agent": agent,
            "mcp": mcp,
            "demo": demo,
        },
        "assertions": dict(sorted(assertions.items())),
        "raw_service_payloads_published": False,
    }
    validate_managed_stack_receipt(receipt)
    return receipt


def validate_managed_stack_receipt(receipt: Mapping[str, Any]) -> None:
    if receipt.get("managed_cloud_claimed") is not True:
        raise ValueError("managed stack receipt must identify its evidence scope")
    assertions = receipt.get("assertions")
    if not isinstance(assertions, Mapping) or set(assertions) != set(STACK_ASSERTIONS):
        raise ValueError("managed stack receipt requires the exact assertions")
    if any(value is not True for value in assertions.values()):
        raise ValueError("managed stack receipt may record only a fully passing run")
    components = receipt.get("components")
    if not isinstance(components, Mapping) or set(components) != {
        "schema",
        "agent",
        "mcp",
        "demo",
    }:
        raise ValueError("managed stack receipt requires all evidence components")
    validate_managed_schema_receipt(components["schema"])
    validate_mcp_receipt(components["mcp"])
    if not _SHA256.fullmatch(str(components["demo"].get("origin_sha256", ""))):
        raise ValueError("managed stack receipt requires a demo-origin fingerprint")

    def inspect(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if _BANNED_KEYS.search(str(key)):
                    raise ValueError(f"managed stack receipt contains prohibited key: {key}")
                inspect(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                inspect(child)
        elif isinstance(value, str) and any(pattern.search(value) for pattern in _BANNED_VALUES):
            raise ValueError("managed stack receipt contains private connection material")

    inspect(receipt)


def write_managed_stack_receipt(path: Path, receipt: Mapping[str, Any]) -> str:
    """Atomically write, reopen, and validate the canonical combined receipt."""

    validate_managed_stack_receipt(receipt)
    payload = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    validate_managed_stack_receipt(json.loads(temporary.read_text(encoding="utf-8")))
    temporary.replace(path)
    return hashlib.sha256(payload).hexdigest()
