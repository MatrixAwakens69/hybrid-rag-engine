# Phase 0 Validation and Regression Gate

## Purpose

Phase 1 must not begin until every required Phase 0 gate passes. Run this same gate
after every later phase so foundational contracts, configuration safety, health
semantics, import boundaries, and container startup cannot silently regress.

The automated runner is the source of truth:

```bash
uv run python scripts/validate_phase_0.py
```

It validates the lock file, installs from the lock, checks style and types, runs
tests with branch coverage, scans for secrets, builds both images, starts Qdrant/API/
worker, waits for health, checks both endpoints, prints service state, and stops the
stack without deleting persistent volumes.

## Prerequisites

From the repository root, confirm:

```bash
python --version
uv --version
docker --version
docker compose version
```

Expected:

- Python is 3.12.x;
- uv is installed;
- Docker Engine is running;
- Docker Compose supports `up --wait`.

The first full run downloads locked Python packages and pinned container images.

## Gate 1 — Reproducible dependencies

```bash
uv lock --check
uv sync --frozen --dev
```

Pass criteria:

- `uv.lock` matches `pyproject.toml`;
- installation succeeds without changing the lock;
- no dependency is resolved dynamically during the frozen sync.

If dependencies intentionally change, run `uv lock`, review the full lock diff, and
rerun every gate. Never repair CI with an unfrozen install.

## Gate 2 — Static quality

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app worker
```

Pass criteria:

- no lint or formatting violations;
- strict type checking passes for runtime code;
- suppressions are narrow and explained.

Do not automatically accept formatting or broad type ignores merely to make the gate
green. Review why the diff is safe.

## Gate 3 — Unit, contract, and architecture regression

```bash
uv run pytest \
  tests/unit \
  tests/contract \
  tests/architecture \
  --cov=app.config \
  --cov=app.api.errors \
  --cov=app.api.health \
  --cov=app.api.middleware \
  --cov=app.domain.models.query \
  --cov=app.infrastructure.qdrant_health \
  --cov=app.main \
  --cov-branch \
  --cov-report=term-missing
```

Pass criteria:

- configuration rejects weak production secrets, unsafe CORS, source-tree runtime
  paths, inconsistent retrieval settings, and unpinned model configuration;
- liveness succeeds without touching Qdrant;
- readiness succeeds only when Qdrant is reachable and returns a safe `503` otherwise;
- request IDs are validated and safe errors contain no internal details;
- answer contracts reject unknown citations and inconsistent answer/abstention states;
- domain, application, and API import boundaries remain intact;
- importing `app.main` does not load Docling, LlamaIndex, RAGAS, Torch, or
  sentence-transformer modules;
- OpenAPI exactly matches the reviewed snapshot;
- branch coverage meets the configured threshold.

### Reviewing an intentional OpenAPI change

First inspect the semantic diff. If it is backward compatible and approved:

```bash
uv run python scripts/export_openapi.py
uv run pytest tests/contract/test_openapi_snapshot.py
```

Commit the code and snapshot together. Never regenerate the snapshot before reviewing
why it changed.

## Gate 4 — Secret scan

The automated runner uses a pinned gitleaks container:

```bash
docker run --rm \
  -v "$PWD:/repo" \
  zricethezav/gitleaks:v8.28.0 \
  detect --source=/repo --config=/repo/.gitleaks.toml --no-git --redact --no-banner
```

Pass criteria: exit code zero and no detected secrets.

`.env.example` contains only the documented development placeholder. Real `.env`
files, API keys, provider credentials, certificates, and generated data must never be
committed.

## Gate 5 — Docker configuration and image builds

```bash
docker compose config --quiet
docker compose build
```

Pass criteria:

- Compose configuration is valid;
- the API and worker images install from `uv.lock`;
- image build does not require local source outside the build context;
- no model artifacts are downloaded during build;
- both runtime images use the non-root `appuser`.

## Gate 6 — Runtime smoke test

```bash
docker compose up --detach --wait
uv run python scripts/smoke_test.py
docker compose ps
```

Pass criteria:

- Qdrant, API, and worker are all `healthy`;
- `/health/live` returns HTTP 200 with `status=ok`;
- `/health/ready` returns HTTP 200, `status=ok`, and a healthy `qdrant` dependency;
- API readiness does not require a collection or call a model provider;
- worker remains alive without claiming jobs during Phase 0.

Inspect responses manually when desired:

```bash
curl -i http://localhost:8000/health/live
curl -i -H "X-Request-ID: phase-0-manual-check" \
  http://localhost:8000/health/ready
```

Both responses must include `X-Request-ID`. Readiness must report only safe dependency
state and latency, never endpoint credentials or exception text.

Stop the stack while retaining named volumes:

```bash
docker compose down
```

Use `docker compose down --volumes` only when intentionally deleting local Qdrant and
source/job data.

## Gate 7 — Manual production-policy review

Automated tests cover these cases, but review them before a production release:

- `.env.example` and Compose contain no real credentials;
- production bootstrap key is supplied at runtime and is at least 32 characters;
- production CORS contains explicit HTTPS origins, never `*`;
- source, manifest, and quarantine paths are outside the application source tree;
- model adapter names and immutable revisions are pinned;
- Qdrant is not exposed publicly in the production network;
- TLS termination and production secret injection have named owners.

Phase 0 does not claim that authentication, ingestion controls, query rate limiting,
RAG retrieval, model validation, backups, or high availability exist. Those controls
remain gated in later phases.

## Exit Checklist

Record the following evidence in the phase/release review:

- [ ] `uv lock --check` and frozen sync passed.
- [ ] Ruff lint and format checks passed.
- [ ] Strict mypy passed.
- [ ] Unit, contract, and architecture tests passed with the configured branch
      coverage threshold.
- [ ] OpenAPI snapshot was unchanged or its change was explicitly reviewed.
- [ ] Secret scan passed.
- [ ] API and worker images built from the lock.
- [ ] Qdrant, API, and worker became healthy in Compose.
- [ ] Liveness and readiness smoke tests passed.
- [ ] Production-policy settings were reviewed.
- [ ] [Threat model](THREAT_MODEL.md) still matches the implemented boundary.

Phase 0 is accepted only when every item is checked. Attach the command output or CI
run to the review; a verbal confirmation is not sufficient.

## Regression Policy for Later Phases

At each future phase:

1. Add tests for the new phase's invariants and abuse cases.
2. Run this complete Phase 0 gate unchanged.
3. Run all earlier phase gates.
4. Run the current phase's quality, security, and operational gates.
5. Review architecture, threat model, OpenAPI, and dependency changes.
6. Record versions and evidence before starting the next phase.

Never weaken an older gate to accommodate a new implementation without documenting
the trade-off, adding equivalent protection, and receiving explicit review.
