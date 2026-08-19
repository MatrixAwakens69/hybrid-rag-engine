# Hybrid RAG Engine

Production-oriented, multi-tenant document retrieval and grounded-answer service
built with Python, FastAPI, Qdrant, LlamaIndex, RAGAS, and Docker.

The project is delivered in gated phases. Phase 0 provides contracts, validated
configuration, health endpoints, project boundaries, Docker scaffolding, CI, and the
regression validation workflow. Ingestion, retrieval, generation, and evaluation are
added in later phases only after the preceding gate passes.

## Local development

Requirements:

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Docker with Compose

Install the locked development environment:

```bash
uv sync --frozen --dev
```

Run the local quality checks:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app worker
uv run pytest tests/unit tests/contract tests/architecture
```

Start the development stack:

```bash
docker compose up --build --wait
```

Verify:

```bash
curl -fsS http://localhost:8000/health/live
curl -fsS http://localhost:8000/health/ready
```

Stop the stack without deleting persistent data:

```bash
docker compose down
```

Use `scripts/validate_phase_1.py` for the complete repeatable Phase 0 and Phase 1
regression gate.

## Configuration

Copy `.env.example` to `.env` for local overrides. Production configuration rejects:

- default or weak bootstrap secrets;
- wildcard, empty, or non-HTTPS CORS origins;
- runtime storage paths inside the application source tree;
- unpinned model adapter and revision settings.

The service never loads model weights merely by importing `app.main`.
