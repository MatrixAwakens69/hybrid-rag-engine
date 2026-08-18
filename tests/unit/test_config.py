"""Configuration and production-policy regression tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Environment, Settings


def _production_settings(tmp_path: Path, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "_env_file": None,
        "environment": Environment.PRODUCTION,
        "bootstrap_admin_key": "a-strong-bootstrap-key-with-32-plus-characters",
        "cors_origins": ["https://app.example.com"],
        "source_volume_path": tmp_path / "sources",
        "job_manifest_path": tmp_path / "jobs",
        "quarantine_path": tmp_path / "quarantine",
        "dense_adapter": "dense-adapter",
        "dense_model_revision": "sha256:dense",
        "sparse_adapter": "sparse-adapter",
        "sparse_model_revision": "sha256:sparse",
        "reranker_adapter": "reranker-adapter",
        "reranker_model_revision": "sha256:reranker",
        "generator_adapter": "generator-adapter",
        "generator_model_revision": "sha256:generator",
        "judge_adapter": "judge-adapter",
        "judge_model_revision": "sha256:judge",
    }
    values.update(overrides)
    return values


def test_development_defaults_are_bounded() -> None:
    settings = Settings(_env_file=None)

    assert settings.environment is Environment.DEVELOPMENT
    assert settings.rerank_top_k <= settings.dense_candidates + settings.sparse_candidates
    assert settings.max_upload_bytes == 50 * 1024 * 1024


def test_rejects_inconsistent_retrieval_limits() -> None:
    with pytest.raises(ValidationError, match="rerank_top_k"):
        Settings(
            _env_file=None,
            dense_candidates=1,
            sparse_candidates=1,
            rerank_top_k=3,
        )


@pytest.mark.parametrize("weak_key", ["", "change-me", "example", "short"])
def test_production_rejects_weak_bootstrap_secrets(tmp_path: Path, weak_key: str) -> None:
    with pytest.raises(ValidationError, match="strong runtime secret"):
        Settings(**_production_settings(tmp_path, bootstrap_admin_key=weak_key))


@pytest.mark.parametrize("origins", [[], ["*"], ["http://app.example.com"]])
def test_production_rejects_unsafe_cors(tmp_path: Path, origins: list[str]) -> None:
    with pytest.raises(ValidationError, match="production CORS"):
        Settings(**_production_settings(tmp_path, cors_origins=origins))


def test_production_rejects_runtime_storage_in_source_tree(tmp_path: Path) -> None:
    source_tree_path = Path(__file__).resolve().parents[2] / "data"
    with pytest.raises(ValidationError, match="outside the application source tree"):
        Settings(**_production_settings(tmp_path, source_volume_path=source_tree_path))


def test_production_rejects_unpinned_model_configuration(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="must be pinned"):
        Settings(**_production_settings(tmp_path, generator_model_revision="not-configured"))


def test_valid_production_configuration_is_accepted(tmp_path: Path) -> None:
    settings = Settings(**_production_settings(tmp_path))

    assert settings.environment is Environment.PRODUCTION
    assert settings.bootstrap_admin_key.get_secret_value().startswith("a-strong")
