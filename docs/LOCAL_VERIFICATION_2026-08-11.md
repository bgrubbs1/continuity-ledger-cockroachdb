# Local verification - 2026-08-11

This record covers credential-free local checks only. It is not evidence of a managed CockroachDB connection, Managed MCP call, AWS deployment, availability, latency, scale, or contest submission.

## Python and policy contracts

- Python 3.12 virtual environment: used.
- `python -m unittest discover -s tests -v`: 45/45 passed.
- `python -m compileall -q src tests scripts`: passed.
- `python -m pip check`: no broken requirements.
- Covered behavior includes tenant-isolated append/search, deterministic embeddings, idempotency, restart persistence, private-marker rejection, bounded serialization retry, JWT-derived tenant identity, cross-tenant spoof rejection, the retrieve-decide-cite-record agent loop, fixed public-demo scenarios, read-only Managed MCP discovery/call enforcement, secret-free Managed MCP receipts, encrypted SSM Parameter Store loading/writing, managed schema bootstrap receipts, release exclusions, and deterministic release manifests.

## Lambda container agent demonstration

- Local image: `continuity-ledger:work`.
- Runtime: official AWS Lambda Python 3.12 container interface.
- Persistence: local SQLite enabled explicitly for this credential-free smoke only.
- `GET /`: returned `200` with the self-contained demo interface.
- `POST /demo/seed`: inserted three fixed fictional memory records.
- `POST /demo/run` for `ingest_backlog`: retrieved and cited `prior_ingest:1`, selected `inspect_ingest_validation`, and persisted the decision.
- Repeating the scenario returned the existing idempotent decision rather than duplicating it.
- An arbitrary scenario was rejected with `400`.
- Unauthenticated access to protected `POST /agent/run` was rejected with `401`.
- The smoke container was removed after verification.

This evidence was produced by `python scripts/smoke_lambda_container.py`. No managed service, credential, private data, or external model was used.

## CockroachDB vector contract

The existing public receipt at `artifacts/public/local-cockroach-contract.json` records a successful disposable-local run against `cockroachdb/cockroach:v26.2.3`. Seven assertions cover schema creation, vector-index presence, idempotent replay blocking, sequence-conflict blocking, tenant isolation, independently calculated cosine similarity, and bounded serialization retry. The receipt explicitly states `managed_cloud_claimed: false`.

## Remaining evidence gates

The project still requires an owner-authorized managed CockroachDB run, one actual read-only Managed MCP operation, AWS deployment, logged-out hosted-demo proof, public video, and final entrant review/submission. Until those occur, no managed-cloud functionality, performance, availability, or persistence claim is made.
