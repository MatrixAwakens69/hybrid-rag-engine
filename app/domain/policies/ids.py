"""Deterministic identifiers for replay-safe ingestion."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID, uuid5

_NAMESPACE = UUID("8e3c478d-a30a-5ba2-a49f-68ef0c80834d")


def _stable_uuid(kind: str, parts: Sequence[object]) -> str:
    value = "\x1f".join([kind, *(str(part) for part in parts)])
    return str(uuid5(_NAMESPACE, value))


def document_version_id(
    tenant_id: str,
    checksum_sha256: str,
    parser_version: str,
    chunker_version: str,
    index_schema_version: str,
) -> str:
    """Identify one source processed by one complete ingestion schema."""

    return _stable_uuid(
        "document-version",
        [tenant_id, checksum_sha256, parser_version, chunker_version, index_schema_version],
    )


def ingestion_job_id(document_id: str, checksum_sha256: str) -> str:
    """Identify an idempotent ingestion delivery."""

    return _stable_uuid("ingestion-job-v1", [document_id, checksum_sha256])


def deletion_job_id(document_id: str) -> str:
    """Identify the one idempotent deletion workflow for a document."""

    return _stable_uuid("deletion-job-v1", [document_id])


def element_id(document_id: str, ordinal: int, text: str) -> str:
    """Identify one normalized source element."""

    return _stable_uuid("element-v1", [document_id, ordinal, text])


def chunk_id(
    document_version: str,
    hierarchy_path: Sequence[str],
    source_span: str,
    ordinal: int,
) -> str:
    """Identify one deterministic, source-traceable chunk."""

    return _stable_uuid(
        "chunk-v1",
        [document_version, "/".join(hierarchy_path), source_span, ordinal],
    )


def control_point_id(kind: str, external_id: str) -> str:
    """Map an external identifier to a Qdrant-compatible UUID point ID."""

    return _stable_uuid(f"control-{kind}", [external_id])
