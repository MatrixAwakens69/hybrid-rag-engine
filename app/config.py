"""Validated, environment-driven application configuration."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Supported deployment environments."""

    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Application settings loaded from ``HRE_*`` environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="HRE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"
    app_revision: str = "local"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    qdrant_url: str = "http://localhost:6333"
    qdrant_timeout_seconds: int = Field(default=5, gt=0, le=60)
    qdrant_collection_alias: str = "hybrid_chunks_current"

    source_volume_path: Path = Path("data/sources")
    job_manifest_path: Path = Path("data/jobs")
    quarantine_path: Path = Path("data/quarantine")

    dense_adapter: str = "not-configured"
    dense_model_revision: str = "not-configured"
    sparse_adapter: str = "not-configured"
    sparse_model_revision: str = "not-configured"
    reranker_adapter: str = "not-configured"
    reranker_model_revision: str = "not-configured"
    generator_adapter: str = "not-configured"
    generator_model_revision: str = "not-configured"
    judge_adapter: str = "not-configured"
    judge_model_revision: str = "not-configured"

    dense_candidates: int = Field(default=50, ge=1, le=1000)
    sparse_candidates: int = Field(default=50, ge=1, le=1000)
    rrf_k: int = Field(default=60, ge=1, le=1000)
    rerank_top_k: int = Field(default=20, ge=1, le=200)
    evidence_score_threshold: float = Field(default=0.0, ge=-1.0, le=1.0)

    max_upload_bytes: int = Field(default=50 * 1024 * 1024, ge=1024, le=1024**3)
    request_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    max_metadata_bytes: int = Field(default=16 * 1024, ge=256, le=1024**2)

    bootstrap_admin_key: SecretStr = SecretStr("change-me")

    @model_validator(mode="after")
    def validate_cross_field_policy(self) -> Self:
        """Reject unsafe or internally inconsistent settings."""

        if self.rerank_top_k > self.dense_candidates + self.sparse_candidates:
            raise ValueError("rerank_top_k cannot exceed all retrieval candidates")

        if self.environment is not Environment.PRODUCTION:
            return self

        self._validate_production_secrets()
        self._validate_production_cors()
        self._validate_production_paths()
        self._validate_production_model_revisions()
        return self

    def _validate_production_secrets(self) -> None:
        key = self.bootstrap_admin_key.get_secret_value().strip()
        unsafe_values = {"", "change-me", "changeme", "example", "default", "secret"}
        if key.lower() in unsafe_values or len(key) < 32:
            raise ValueError("production bootstrap_admin_key must be a strong runtime secret")

    def _validate_production_cors(self) -> None:
        if not self.cors_origins or "*" in self.cors_origins:
            raise ValueError("production CORS origins must be an explicit non-empty allowlist")
        if any(origin.startswith("http://") for origin in self.cors_origins):
            raise ValueError("production CORS origins must use HTTPS")

    def _validate_production_paths(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        for name, configured_path in (
            ("source_volume_path", self.source_volume_path),
            ("job_manifest_path", self.job_manifest_path),
            ("quarantine_path", self.quarantine_path),
        ):
            resolved = configured_path.expanduser().resolve()
            if resolved == project_root or project_root in resolved.parents:
                raise ValueError(f"production {name} must be outside the application source tree")

    def _validate_production_model_revisions(self) -> None:
        values = {
            "dense_adapter": self.dense_adapter,
            "dense_model_revision": self.dense_model_revision,
            "sparse_adapter": self.sparse_adapter,
            "sparse_model_revision": self.sparse_model_revision,
            "reranker_adapter": self.reranker_adapter,
            "reranker_model_revision": self.reranker_model_revision,
            "generator_adapter": self.generator_adapter,
            "generator_model_revision": self.generator_model_revision,
            "judge_adapter": self.judge_adapter,
            "judge_model_revision": self.judge_model_revision,
        }
        missing = sorted(name for name, value in values.items() if value == "not-configured")
        if missing:
            raise ValueError(f"production model adapters and revisions must be pinned: {missing}")


@lru_cache
def get_settings() -> Settings:
    """Load and cache process-wide settings."""

    return Settings()
