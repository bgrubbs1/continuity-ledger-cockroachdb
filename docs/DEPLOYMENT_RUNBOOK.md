# Managed deployment runbook

This runbook is intentionally fail-closed. It must be used only with owner-authorized contest accounts, fictional data, and free-tier or explicitly approved credits. Never paste a connection string, token, account ID, or billing value into a public issue, command log, video, or submission field.

## Prerequisites

- Python 3.12 and the project virtual environment;
- Docker Desktop;
- AWS CLI and AWS SAM CLI authenticated to the contest-only AWS account;
- a contest-only CockroachDB Cloud connection string stored in a local ignored file;
- a read-only CockroachDB Managed MCP credential stored only in local secret storage;
- an AWS region selected by the entrant.

Before any managed action, confirm the local suite remains green:

```powershell
.\.venv\Scripts\python -m pip install -e ".[cloud,dev]"
.\.venv\Scripts\python -m unittest discover -s tests -v
.\.venv\Scripts\python -m compileall -q src tests scripts
.\.venv\Scripts\python -m pip check
```

## 1. Load the connection string without printing it

Store the complete CockroachDB connection string in a private file outside the repository. Load it only into the current process:

```powershell
$privateUrlFile = Join-Path $env:USERPROFILE '.continuity-ledger\database-url.txt'
if (-not (Test-Path -LiteralPath $privateUrlFile)) { throw 'Private database URL file is missing' }
$env:DATABASE_URL = (Get-Content -Raw -LiteralPath $privateUrlFile).Trim()
if (-not $env:DATABASE_URL.StartsWith('postgresql://')) { throw 'Unexpected database URL scheme' }
```

Do not echo `$env:DATABASE_URL`.

## 2. Bootstrap and verify the managed schema

```powershell
.\.venv\Scripts\python scripts\bootstrap_managed_schema.py `
  --receipt artifacts\private\managed-schema-bootstrap.json
```

The command is idempotent and verifies the table plus vector index. Its terminal output and receipt exclude the connection string and endpoint. Keep the first receipt private until it has been independently scanned and promoted to `artifacts/public`.

## 3. Store the URL in encrypted AWS Parameter Store

Set the region explicitly, verify the signed-in identity locally, and write a Standard-tier `SecureString`:

```powershell
$env:AWS_REGION = 'us-east-1' # replace only if the authorized account uses another region
aws sts get-caller-identity
.\.venv\Scripts\python scripts\put_aws_database_parameter.py `
  --name /continuity-ledger/database-url `
  --receipt artifacts\private\aws-parameter-store.json
```

The helper passes the secret through the SDK rather than a command-line argument. The receipt includes only a hash of the parameter name, its type/tier, and the returned version.

## 4. Build and deploy the Lambda image

```powershell
sam validate --lint --template-file deployment\template.yaml
sam build --template-file deployment\template.yaml
sam deploy --guided `
  --stack-name continuity-ledger-contest `
  --capabilities CAPABILITY_IAM `
  --parameter-overrides `
    DatabaseParameterName=/continuity-ledger/database-url `
    JwtIssuer=https://example.invalid/continuity-ledger `
    JwtAudience=continuity-ledger-demo
```

The placeholder JWT issuer intentionally makes protected routes unusable until a real identity provider is configured. The fixed public demo routes remain accessible. Never claim authenticated-user functionality from the placeholder configuration.

Capture the `DemoUrl` output without exposing account identifiers or stack internals. Confirm the Lambda role can read only the named SSM parameter.

## 5. Verify the hosted fixed-scenario demo

From a logged-out browser:

1. open the `DemoUrl` and confirm the page contains no account or tenant control;
2. seed the fixed fictional memories;
3. run `Ingest backlog` and confirm the action cites `prior_ingest:1`;
4. repeat it and confirm the decision is reused rather than duplicated;
5. run the review-status scenario and confirm the agent recommends a fresh status check without inventing a root cause;
6. confirm arbitrary text cannot be entered;
7. confirm unauthenticated protected routes remain rejected.

Save only cropped evidence that shows the fictional scenario, citation, action, and managed service identity. Exclude browser profiles, account IDs, URLs containing secrets, bookmarks, other tabs, and system notifications.

## 6. Verify one read-only Managed MCP operation

Load `COCKROACH_MCP_URL`, `COCKROACH_CLUSTER_ID`, and `COCKROACH_MCP_TOKEN` into the current process from local secret storage. Do not print them. Then:

```powershell
.\.venv\Scripts\python scripts\verify_managed_mcp.py `
  --tool list_databases `
  --arguments-json '{}' `
  --receipt artifacts\private\managed-mcp-readonly.json
```

The client discovers the server tools, refuses any tool outside its read-only allowlist, executes the named operation, and writes only structural result metadata. Promote the receipt publicly only after a separate secret and privacy scan.

## 7. Collect the combined managed-stack receipt

After the schema, deployment, and MCP credential are available in the current process, set the public `DemoUrl` without printing any other value:

```powershell
$env:CONTINUITY_DEMO_URL = 'https://replace-with-the-deployed-demo-origin'
.\.venv\Scripts\python scripts\verify_managed_stack.py `
  --receipt artifacts\private\managed-stack-evidence.json
```

This is the decisive end-to-end verifier. It bootstraps and verifies the managed schema, runs the fixed synthetic ingest scenario through CockroachDB retrieve-decide-cite-record memory, performs the allowlisted `list_databases` MCP call, and checks the public AWS demo plus rejection of anonymous access to the protected agent route. The receipt is written atomically only if every phase passes. It retains only structural assertions, counts, action/citation metadata, hashes, and a hash of the demo origin—never the origin, database URL, cluster ID, token, account ID, or raw service output.

Keep the first combined receipt private until it passes an independent privacy/secret scan. Do not describe the managed stack as verified merely because this command exists.

## 8. Final evidence and cleanup

- rerun the full local suite and public-release builder;
- verify all public receipts by hash and reopen them;
- scan screenshots/video frames and the repository for credentials and private identifiers;
- verify the demo URL while logged out;
- retain the hosted demo through the judging period;
- after judging, remove the stack, SSM parameter, service credentials, and database resources if no longer needed.

Managed deployment is proven only after every applicable step above succeeds and the sanitized evidence is retained. A prepared command or local mock is not managed-cloud evidence.
