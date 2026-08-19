"""Detect accidental public API contract changes."""

from __future__ import annotations

import json
from pathlib import Path

from app.config import Environment, Settings
from app.main import create_app

SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "openapi.json"


def test_openapi_matches_reviewed_snapshot() -> None:
    settings = Settings(_env_file=None, environment=Environment.TEST, app_revision="contract")
    actual = create_app(settings).openapi()
    expected = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))

    assert actual == expected, (
        "OpenAPI changed. Review compatibility, then run "
        "`uv run python scripts/export_openapi.py` to accept the new contract."
    )


def test_phase_one_exposes_only_health_and_document_routes() -> None:
    settings = Settings(_env_file=None, environment=Environment.TEST)
    paths = set(create_app(settings).openapi()["paths"])

    assert paths == {
        "/health/live",
        "/health/ready",
        "/v1/documents",
        "/v1/documents/{document_id}",
    }
