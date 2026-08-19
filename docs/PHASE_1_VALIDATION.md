# Phase 1 Validation and Regression Gate

## Required Gate

Do not begin Phase 2 until this command passes:

```bash
uv run python scripts/validate_phase_1.py
```

It first runs the complete Phase 0 gate unchanged, then installs the locked ingestion
extra, runs all Phase 1 tests, starts the Docker stack, and verifies the authenticated
upload → processing → inspection → idempotent re-upload → deletion lifecycle.

Docker Desktop must be running. The first worker build downloads the pinned Docling
dependency set and is substantially larger than the API image.

## Manual Code Validation

```bash
uv lock --check
uv sync --frozen --dev --extra ingestion
uv run ruff check .
uv run ruff format --check .
uv run mypy app worker
uv run pytest tests/unit tests/contract tests/architecture tests/security tests/integration \
  --cov=app --cov-branch --cov-report=term-missing
```

Pass criteria:

- all Phase 0 configuration, health, import-boundary, OpenAPI, and container tests pass;
- deterministic ID, lifecycle, upload, manifest, parser, and chunker tests pass;
- tenant A cannot get or delete tenant B documents;
- missing or invalid bearer tokens return a safe `401`;
- MIME spoofing, reserved metadata, binary text, and oversized streams are rejected;
- duplicate upload produces the same document ID and no duplicate job;
- parser failure reaches terminal `failed` while the worker remains usable;
- deletion removes source and derived artifacts;
- coverage remains at or above the configured 85% branch-aware threshold.

## Manual Docker Validation

Start the complete stack:

```bash
docker compose up --build --detach --wait
docker compose ps
```

Expected services: `qdrant`, `api`, and `worker` are all healthy.

Run the repeatable authenticated lifecycle smoke test:

```bash
uv run python scripts/smoke_phase_1.py
```

The script uses the development bootstrap key `change-me`, uploads a Markdown file,
polls until `ready`, verifies idempotent re-upload and listing, deletes it, and polls
until `deleted`.

To use a non-default key or endpoint:

```powershell
$env:PHASE1_API_KEY = "your-runtime-key"
$env:PHASE1_BASE_URL = "http://127.0.0.1:8000"
uv run python scripts/smoke_phase_1.py
```

Provision or rotate a separate tenant key while Qdrant is running:

```bash
uv run python scripts/provision_api_key.py --tenant-id tenant-acme --key-id acme-primary
```

The raw `key_id.secret` token is printed once; store it in the deployment secret
system. Qdrant receives only its Argon2 hash.

## Manual API Inspection

Create a temporary file:

```powershell
Set-Content -Path phase1-manual.md -Value "# Evidence`n`nPhase 1 manual validation."
```

Upload it:

```powershell
curl.exe -sS -X POST "http://127.0.0.1:8000/v1/documents" `
  -H "Authorization: Bearer $env:PHASE1_API_KEY" `
  -F "metadata_json={\"purpose\":\"manual-validation\"}" `
  -F "file=@phase1-manual.md;type=text/markdown"
```

Copy `document_id` from the response, then inspect:

```powershell
$documentId = "<document_id>"
curl.exe -sS "http://127.0.0.1:8000/v1/documents/$documentId" `
  -H "Authorization: Bearer $env:PHASE1_API_KEY"
curl.exe -sS "http://127.0.0.1:8000/v1/documents" `
  -H "Authorization: Bearer $env:PHASE1_API_KEY"
```

The status progresses through `accepted`, `parsing`, `chunking`, `indexing`, and
`ready`. The API intentionally reports `ready` after durable Phase 1 chunk artifacts;
dense/sparse vector indexing begins in Phase 2.

Delete and verify:

```powershell
curl.exe -sS -X DELETE "http://127.0.0.1:8000/v1/documents/$documentId" `
  -H "Authorization: Bearer $env:PHASE1_API_KEY"
curl.exe -sS "http://127.0.0.1:8000/v1/documents/$documentId" `
  -H "Authorization: Bearer $env:PHASE1_API_KEY"
Remove-Item phase1-manual.md
```

The terminal status must be `deleted`.

## Security Checks

Missing authentication must fail:

```powershell
curl.exe -i "http://127.0.0.1:8000/v1/documents"
```

Expected: HTTP `401`, `WWW-Authenticate: Bearer`, and error code `invalid_api_key`.

A malformed PDF must fail before processing:

```powershell
Set-Content -Path fake.pdf -Value "not a PDF"
curl.exe -i -X POST "http://127.0.0.1:8000/v1/documents" `
  -H "Authorization: Bearer $env:PHASE1_API_KEY" `
  -F "file=@fake.pdf;type=application/pdf"
Remove-Item fake.pdf
```

Expected: HTTP `415` with `unsupported_media_type`, no worker crash, and no promoted
source artifact.

## Shutdown

```bash
docker compose down
```

Do not add `--volumes` unless local Qdrant and document data should be destroyed.

## Exit Checklist

- [ ] `scripts/validate_phase_1.py` passes without skipped gates.
- [ ] Phase 0 regression gate still passes.
- [ ] OpenAPI snapshot intentionally includes only health and document routes.
- [ ] Authenticated upload, status, list, idempotent re-upload, and delete pass.
- [ ] Cross-tenant get/delete tests return indistinguishable `404` responses.
- [ ] Every generated chunk records tenant, checksum, source span, parser version,
      chunker version, and deterministic ID.
- [ ] Corrupt/empty parser cases become terminal `failed`; worker stays healthy.
- [ ] Secret scan and Docker non-root checks pass.
- [ ] [Threat model](THREAT_MODEL.md) reflects Phase 1 controls and residual risks.

Repeat this complete gate before every Phase 2 change is accepted.
