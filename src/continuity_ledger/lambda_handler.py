"""AWS Lambda/API Gateway adapter. It fails closed without a configured store."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

from .agent import ContinuityAgent
from .aws_config import resolve_database_url
from .cockroach import CockroachLedgerStore, psycopg_connection_factory
from .demo import DEMO_HTML, run_demo_scenario, scenario_catalog, seed_demo_memory
from .models import LedgerEvent
from .service import ContinuityService
from .store import SQLiteLedgerStore


_TENANT_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class RequestAuthorizationError(ValueError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def build_service() -> ContinuityService:
    if os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PARAMETER_NAME"):
        database_url = resolve_database_url()
        return ContinuityService(CockroachLedgerStore(psycopg_connection_factory(database_url)))
    if os.environ.get("ALLOW_LOCAL_SQLITE", "false").lower() == "true":
        return ContinuityService(SQLiteLedgerStore(os.environ.get("SQLITE_PATH", ":memory:")))
    raise RuntimeError("No authorized persistence backend configured")


def make_handler(service_factory: Callable[[], ContinuityService]) -> Callable[[dict[str, Any], Any], dict[str, Any]]:
    def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
        try:
            route = event.get("rawPath") or event.get("path") or ""
            method = (event.get("requestContext", {}).get("http", {}).get("method") or event.get("httpMethod") or "").upper()
            if route == "/healthz" and method == "GET":
                return _response(200, {"status": "ok", "mode": "synthetic-only"})
            if route == "/" and method == "GET":
                return _html_response(200, DEMO_HTML)
            if route == "/demo/scenarios" and method == "GET":
                return _response(200, {"scenarios": scenario_catalog()})
            if route == "/demo/seed" and method == "POST":
                service = service_factory()
                return _response(200, {"memory": seed_demo_memory(service)})
            if route == "/demo/run" and method == "POST":
                body = json.loads(event.get("body") or "{}")
                if not isinstance(body, dict):
                    raise ValueError("request body must be a JSON object")
                service = service_factory()
                outcome = run_demo_scenario(service, body.get("scenario_id", ""))
                if outcome is None:
                    return _response(409, {"error": "seed durable demo memory first"})
                return _response(
                    200,
                    {
                        "action": outcome.action,
                        "rationale": outcome.rationale,
                        "citations": list(outcome.citations),
                        "recalled_count": outcome.recalled_count,
                        "decision_persisted": outcome.decision_recorded,
                        "data_boundary": "fixed fictional scenario",
                    },
                )
            if (route, method) not in {
                ("/events", "POST"),
                ("/search", "POST"),
                ("/agent/run", "POST"),
            }:
                return _response(404, {"error": "route not found"})
            body = json.loads(event.get("body") or "{}")
            if not isinstance(body, dict):
                raise ValueError("request body must be a JSON object")
            tenant_id = _authorized_tenant(event, body)
            service = service_factory()
            if route == "/events" and method == "POST":
                record_payload = dict(body)
                record_payload["tenant_id"] = tenant_id
                record = LedgerEvent(**record_payload)
                return _response(201, {"inserted": service.record(record)})
            if route == "/search" and method == "POST":
                results = service.recall(tenant_id, body["query"], int(body.get("limit", 3)))
                return _response(200, {"results": [
                    {"incident_id": result.event.incident_id, "sequence": result.event.sequence,
                     "summary": result.event.summary, "score": round(result.score, 6)}
                    for result in results
                ]})
            if route == "/agent/run" and method == "POST":
                outcome = ContinuityAgent(service).run(
                    tenant_id=tenant_id,
                    incident_id=body["incident_id"],
                    sequence=int(body["sequence"]),
                    observation=body["observation"],
                    idempotency_key=body["idempotency_key"],
                    created_at=body.get("created_at"),
                )
                return _response(
                    200,
                    {
                        "action": outcome.action,
                        "rationale": outcome.rationale,
                        "citations": list(outcome.citations),
                        "recalled_count": outcome.recalled_count,
                        "observation_recorded": outcome.observation_recorded,
                        "decision_recorded": outcome.decision_recorded,
                    },
                )
        except RequestAuthorizationError as exc:
            return _response(exc.status_code, {"error": str(exc)})
        except (KeyError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            return _response(400, {"error": str(exc)})
    return handler


def _authorized_tenant(event: dict[str, Any], body: dict[str, Any]) -> str:
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    )
    tenant_id = claims.get("tenant_id") if isinstance(claims, dict) else None
    if not isinstance(tenant_id, str) or not tenant_id:
        raise RequestAuthorizationError(401, "verified tenant identity is required")
    if not _TENANT_ID.fullmatch(tenant_id):
        raise RequestAuthorizationError(403, "verified tenant identity is invalid")
    requested_tenant = body.get("tenant_id")
    if requested_tenant is not None and requested_tenant != tenant_id:
        raise RequestAuthorizationError(403, "request tenant does not match verified identity")
    return tenant_id


def _response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {"statusCode": status, "headers": {"content-type": "application/json"}, "body": json.dumps(body)}


def _html_response(status: int, body: str) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "text/html; charset=utf-8"},
        "body": body,
    }


lambda_handler = make_handler(build_service)
