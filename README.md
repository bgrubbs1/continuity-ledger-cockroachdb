# Continuity Ledger

Continuity Ledger is a privacy-first incident-handoff service designed for the CockroachDB × AWS AI Hackathon. It stores an append-only trail of deliberately fictional agent decisions and retrieves relevant prior evidence without crossing tenant boundaries.

## What is implemented locally

- deterministic 32-dimensional feature hashing for reproducible synthetic demos;
- append-only, idempotent event storage with per-tenant isolation;
- API Gateway JWT tenant binding: write and search operations derive the tenant from a verified claim and reject body-based cross-tenant selection;
- a SQLite reference store used only for local contract and restart tests;
- a CockroachDB adapter with `VECTOR(32)`, a vector index, tenant-scoped similarity search, and bounded SQLSTATE `40001` transaction retries;
- a fail-closed managed CockroachDB MCP configuration boundary;
- an AWS Lambda/API Gateway-compatible handler;
- synthetic-only privacy checks that reject common personal, credential, work, home, and private-network markers.

The feature hasher is a deterministic demo encoder, not a trained embedding model or an LLM. No cloud deployment, managed MCP call, availability result, latency result, or contest submission is claimed yet.

## Local verification

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\python -m unittest discover -s tests -v
```

The tests use fictional tenants and incidents. They do not require credentials, network access, CockroachDB Cloud, or AWS.

The SAM template protects `/events` and `/search` with a default JWT authorizer while leaving only `/healthz` public. The Lambda handler independently enforces the verified `tenant_id` claim, so a caller cannot select a different tenant by changing the request body.

## Reproduce the local CockroachDB contract

With Docker running and the optional cloud dependencies installed, execute:

```powershell
python scripts/verify_local_cockroach.py
```

The verifier starts the pinned `cockroachdb/cockroach:v26.2.3` image as a secure,
loopback-only, in-memory single node; creates a fresh ephemeral database user;
exercises the real `CockroachLedgerStore`; verifies the vector index,
idempotency, sequence uniqueness, tenant isolation, similarity calculation, and
bounded serialization retry; writes a secret-free receipt to
`artifacts/public/local-cockroach-contract.json`; and always removes the
container. It does not contact CockroachDB Cloud or AWS.

The exact local evidence from the first verified build is recorded in
[`docs/LOCAL_VERIFICATION_2026-08-09.md`](docs/LOCAL_VERIFICATION_2026-08-09.md).

## Build the public repository candidate

The working folder contains private owner handoff shortcuts and generated local
evidence that must never be published by broad staging. Build a new,
allowlisted candidate instead:

```powershell
python scripts/build_public_release.py --output build/public-repo
```

The destination must not already exist. The builder copies only the declared
application, deployment, test, documentation, and public-evidence paths, then
writes `RELEASE_MANIFEST.json` with the size and SHA-256 of every copied file.
It excludes the owner handoff, contest/signup shortcuts, environments, caches,
private artifacts, and build output. The manifest explicitly records that no
managed CockroachDB Cloud or AWS evidence is claimed.

The credential-free GitHub Actions workflow rebuilds the candidate, verifies
its manifest and exclusions, reruns the full test suite from the clean tree,
compiles the source, and builds the Lambda container. It does not deploy or use
cloud credentials.

## Planned contest integration

1. Provision a contest-only CockroachDB Cloud cluster after Bradley accepts the account terms.
2. Run the schema and reproduce tenant isolation, vector retrieval, idempotency, and retry evidence against that cluster.
3. Connect CockroachDB managed MCP read-only first, then capture only synthetic schema/query evidence.
4. Deploy the Lambda container behind API Gateway in a contest-only AWS account.
5. Publish a public repository, hosted demo, and under-three-minute video only after logged-out verification and a privacy scan.

See [PRIVACY_BOUNDARY.md](PRIVACY_BOUNDARY.md) for the non-negotiable data boundary.
