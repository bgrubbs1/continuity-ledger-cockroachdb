# Continuity Ledger

Continuity Ledger is a privacy-first agent-memory application for the CockroachDB x AWS Hackathon. An agent recalls tenant-scoped incident handoffs, selects a bounded reversible next action, cites the memory supporting that action, and appends its decision to an auditable ledger.

The repository uses only fixed fictional incidents. It contains no employer, customer, household, location, credential, or other private operational data.

## What is implemented

- an append-only, idempotent memory ledger with strict tenant isolation;
- deterministic 32-dimensional feature hashing for reproducible synthetic demonstrations;
- an agent loop that retrieves relevant handoffs, selects or abstains from a bounded action, cites the supporting event, and persists its decision;
- a CockroachDB adapter using `VECTOR(32)`, a vector index, tenant-scoped similarity search, and bounded SQLSTATE `40001` transaction retries;
- a read-only CockroachDB Managed MCP client that discovers an allowlisted tool and rejects write-capable tools before opening a session;
- an AWS Lambda/API Gateway handler with JWT-derived tenant identity;
- encrypted database-URL retrieval from AWS Systems Manager Parameter Store for managed deployment;
- a self-contained public demo with three fixed synthetic scenarios and no arbitrary text input;
- an allowlisted, manifest-hashed public-release builder and credential-free CI verification.

The feature hasher is a deterministic demo encoder, not a trained embedding model or an LLM. The agentic behavior is the evidence-bound retrieve-decide-cite-record loop. No managed CockroachDB call, AWS deployment, availability result, latency result, or contest submission is claimed by this repository yet.

## Public demo contract

The Lambda handler exposes these public synthetic-demo routes:

- `GET /` - self-contained demo interface;
- `GET /demo/scenarios` - the fixed fictional scenario catalog;
- `POST /demo/seed` - idempotently seeds three synthetic handoffs;
- `POST /demo/run` - runs one allowlisted scenario through the memory/action loop.

Protected routes (`/events`, `/search`, and `/agent/run`) derive `tenant_id` from the API Gateway JWT claim. Supplying a different tenant in a request body is rejected. The public demo never accepts arbitrary incident text and always uses the fixed tenant `demo_studio`.

## Local verification

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[cloud,dev]"
.\.venv\Scripts\python -m unittest discover -s tests -v
.\.venv\Scripts\python -m compileall -q src tests scripts
.\.venv\Scripts\python -m pip check
```

The tests use fictional tenants and incidents. They do not require credentials, network access, CockroachDB Cloud, or AWS.

To reproduce the packaged Lambda demo locally:

```powershell
docker build -f deployment/Dockerfile -t continuity-ledger:local .
docker run --rm -p 127.0.0.1:18082:8080 `
  -e ALLOW_LOCAL_SQLITE=true `
  -e SQLITE_PATH=/tmp/demo.sqlite `
  continuity-ledger:local
# In a second terminal:
.\.venv\Scripts\python scripts\smoke_lambda_container.py
```

The smoke verifier checks the home page, synthetic seeding, cited agent action, idempotent replay, rejection of an arbitrary scenario, and rejection of unauthenticated protected-agent access.

Fresh credential-free evidence is recorded in [`docs/LOCAL_VERIFICATION_2026-08-11.md`](docs/LOCAL_VERIFICATION_2026-08-11.md).

## Reproduce the local CockroachDB contract

With Docker running and the optional cloud dependencies installed:

```powershell
.\.venv\Scripts\python scripts\verify_local_cockroach.py
```

The verifier starts the pinned `cockroachdb/cockroach:v26.2.3` image as a loopback-only, in-memory single node; creates a fresh ephemeral database user; exercises the real `CockroachLedgerStore`; verifies the vector index, idempotency, sequence uniqueness, tenant isolation, similarity calculation, and bounded serialization retry; writes a secret-free receipt to `artifacts/public/local-cockroach-contract.json`; and always removes the container. It does not contact CockroachDB Cloud or AWS.

## Managed deployment boundaries

The managed Lambda reads its database URL from an encrypted AWS Systems Manager Parameter Store `SecureString` named by `DATABASE_PARAMETER_NAME`. The direct `DATABASE_URL` environment variable is accepted only for explicit local verification. The helper `scripts/put_aws_database_parameter.py` writes a Standard-tier encrypted parameter and emits a receipt that never includes the value.

`scripts/bootstrap_managed_schema.py` initializes and verifies the CockroachDB schema idempotently. `scripts/verify_managed_mcp.py` performs one allowlisted, read-only Managed MCP operation and writes a secret-free receipt. These scripts require owner-authorized contest accounts and are not evidence that a managed run has happened.

## Build the public repository candidate

The working folder contains private owner handoff shortcuts and generated local material that must never be published by broad staging. Build a new allowlisted candidate instead:

```powershell
.\.venv\Scripts\python scripts/build_public_release.py --output build/public-repo
```

The destination must not already exist. The builder copies only declared application, deployment, test, documentation, and public-evidence paths, then writes `RELEASE_MANIFEST.json` with the size and SHA-256 of every copied file. It excludes account shortcuts, the owner handoff, environments, caches, private artifacts, and build output. The manifest explicitly records that no managed CockroachDB Cloud or AWS evidence is claimed.

The credential-free GitHub Actions workflow rebuilds the candidate, verifies its manifest and exclusions, reruns the test suite from the clean tree, compiles the source, builds the Lambda container, and exercises the complete fixed-scenario agent smoke. It does not deploy or use cloud credentials.

## Remaining contest evidence

Before final submission, the project still needs:

1. an owner-authorized managed CockroachDB schema bootstrap and synthetic vector-memory run;
2. a real read-only CockroachDB Managed MCP call as the second CockroachDB tool;
3. an AWS Lambda/API Gateway deployment using Parameter Store;
4. a logged-out functional demo check;
5. a public under-three-minute video showing CockroachDB memory influencing the agent action;
6. final Devpost review and submission by the entrant.

See [PRIVACY_BOUNDARY.md](PRIVACY_BOUNDARY.md) for the non-negotiable data boundary.
