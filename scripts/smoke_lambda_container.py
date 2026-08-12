#!/usr/bin/env python3
"""Exercise the credential-free Lambda container through its runtime API."""

from __future__ import annotations

import argparse
import json
import urllib.request


def invoke(endpoint: str, event: dict[str, object]) -> dict[str, object]:
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(event).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        outer = json.loads(response.read().decode("utf-8"))
    if not isinstance(outer, dict) or "statusCode" not in outer:
        raise RuntimeError("Lambda runtime returned an invalid response contract")
    return outer


def json_body(response: dict[str, object]) -> dict[str, object]:
    body = json.loads(str(response.get("body", "")))
    if not isinstance(body, dict):
        raise RuntimeError("Lambda response body must be a JSON object")
    return body


def run_smoke(endpoint: str) -> dict[str, object]:
    home = invoke(
        endpoint,
        {"rawPath": "/", "requestContext": {"http": {"method": "GET"}}},
    )
    if home["statusCode"] != 200 or not str(home.get("headers", {}).get("content-type", "")).startswith("text/html"):
        raise RuntimeError("public demo home contract failed")

    seed = invoke(
        endpoint,
        {
            "rawPath": "/demo/seed",
            "requestContext": {"http": {"method": "POST"}},
            "body": "{}",
        },
    )
    seed_body = json_body(seed)
    if seed["statusCode"] != 200 or seed_body["memory"]["inserted"] != 3:
        raise RuntimeError("public demo seed contract failed")

    run_event = {
        "rawPath": "/demo/run",
        "requestContext": {"http": {"method": "POST"}},
        "body": json.dumps({"scenario_id": "ingest_backlog"}),
    }
    first = invoke(endpoint, run_event)
    first_body = json_body(first)
    if (
        first["statusCode"] != 200
        or first_body["action"] != "inspect_ingest_validation"
        or first_body["citations"] != ["prior_ingest:1"]
        or first_body["data_boundary"] != "fixed fictional scenario"
    ):
        raise RuntimeError("public demo memory-action contract failed")

    repeated = invoke(endpoint, run_event)
    repeated_body = json_body(repeated)
    if repeated["statusCode"] != 200 or repeated_body["decision_persisted"] is not False:
        raise RuntimeError("public demo idempotency contract failed")

    rejected = invoke(
        endpoint,
        {
            "rawPath": "/demo/run",
            "requestContext": {"http": {"method": "POST"}},
            "body": json.dumps(
                {"scenario_id": "arbitrary", "observation": "must not be accepted"}
            ),
        },
    )
    if rejected["statusCode"] != 400:
        raise RuntimeError("public demo allowlist contract failed")

    unauthorized = invoke(
        endpoint,
        {
            "rawPath": "/agent/run",
            "requestContext": {"http": {"method": "POST"}},
            "body": "{}",
        },
    )
    if unauthorized["statusCode"] != 401:
        raise RuntimeError("protected agent authorization contract failed")

    return {
        "status": "verified",
        "home_status": home["statusCode"],
        "seeded_memories": seed_body["memory"]["inserted"],
        "agent_action": first_body["action"],
        "citation": first_body["citations"][0],
        "repeat_was_idempotent": True,
        "arbitrary_scenario_rejected": True,
        "unauthenticated_agent_rejected": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--endpoint",
        default="http://127.0.0.1:18082/2015-03-31/functions/function/invocations",
    )
    args = parser.parse_args(argv)
    print(json.dumps(run_smoke(args.endpoint), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
