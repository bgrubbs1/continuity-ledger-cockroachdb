# Local verification — 2026-08-09

This record covers credential-free local checks only. It is not evidence of a cloud deployment, managed MCP connection, regional failover, availability, latency, scale, or contest submission.

## Python contract

- Python 3.12 package build and installed-package import: passed.
- `python -m unittest discover -s tests -v`: 18/18 passed.
- `python -m compileall -q src tests scripts`: passed.
- Covered behavior: deterministic normalized feature hashing; append-only sequence uniqueness; idempotency; tenant-scoped retrieval; local restart persistence; private-marker rejection; bounded SQLSTATE 40001 retries; non-retryable failure handling; HTTPS/fail-closed managed MCP configuration; secret-free MCP summaries; Lambda record/search/health contracts; verified JWT tenant derivation; missing-identity rejection; cross-tenant request rejection; and SAM JWT-authorizer routing.

## AWS Lambda container contract

- Base: official `public.ecr.aws/lambda/python:3.12` image resolved during the build.
- Local image: `continuity-ledger-local:test`.
- Docker build: passed.
- Lambda Runtime Interface Emulator invocation of `GET /healthz`: HTTP contract returned `200`, `status=ok`, `mode=synthetic-only`.
- Lambda Runtime Interface Emulator invocation of unauthenticated `POST /search`: HTTP contract returned `401` before persistence initialization.
- The SAM template applies its JWT authorizer to `/events` and `/search`, explicitly exempts `/healthz`, and passes a parsed infrastructure-contract test.
- Health verification intentionally performed no persistence initialization and no external request.

## CockroachDB vector contract

- Reproduction command: `python scripts/verify_local_cockroach.py`.
- Official image: `cockroachdb/cockroach:v26.2.3`, resolved digest `sha256:1073844226a6291b8a44fcb9cab5cb02035bb8fea3266dcc5dd021c0b34484a0`.
- Container storage: ephemeral in-memory secure single-node instance; a random ephemeral database password existed only for the disposable run.
- The real `CockroachLedgerStore` initialized `ledger_events` with `VECTOR(32)` and the `ledger_events_embedding_idx` vector index.
- Seven assertions passed: schema creation, vector-index presence, idempotent replay blocking, sequence-conflict blocking, tenant isolation, an independently calculated cosine-similarity match, and bounded serialization retry.
- Sanitized receipt: `artifacts/public/local-cockroach-contract.json`, SHA-256 `b56f7fead23b91d6c6ca4a9c57dc6c03c51a50b6e2bc9d4843e5fe2795110a20`.
- The verifier stopped and removed the container in `finally`; no contest, personal, household, work, or customer data was used.

## Remaining evidence gates

Bradley must personally accept the contest, CockroachDB Cloud, and AWS terms before any real account use. After that gate, the project still needs a contest-only managed CockroachDB deployment, an authorized managed MCP run, a real AWS Lambda/API Gateway deployment, logged-out functional proof, a public repository, a public demo video, and final Devpost review/submission.
