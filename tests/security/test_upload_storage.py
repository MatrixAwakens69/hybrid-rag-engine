"""Streaming upload bounds and safe path generation."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.errors import UploadTooLargeError
from app.domain.models import TenantPrincipal
from app.infrastructure.filesystem.document_storage import DocumentFileStorage


async def _chunks(*values: bytes):
    for value in values:
        yield value


@pytest.mark.asyncio
async def test_oversized_stream_is_removed_from_quarantine(tmp_path: Path) -> None:
    storage = DocumentFileStorage(tmp_path / "quarantine", tmp_path / "sources")
    await storage.initialize()
    principal = TenantPrincipal(tenant_id="tenant-a", key_id="key-a")

    with pytest.raises(UploadTooLargeError):
        await storage.stage(principal, _chunks(b"1234", b"5678"), max_bytes=5)

    assert not list((tmp_path / "quarantine").rglob("*.part"))


@pytest.mark.asyncio
async def test_promoted_source_path_uses_only_server_identifiers(tmp_path: Path) -> None:
    storage = DocumentFileStorage(tmp_path / "quarantine", tmp_path / "sources")
    await storage.initialize()
    principal = TenantPrincipal(tenant_id="tenant-a", key_id="key-a")
    staged = await storage.stage(principal, _chunks(b"content"), max_bytes=100)

    destination = await storage.promote(
        staged,
        principal,
        "00000000-0000-5000-8000-000000000001",
        ".txt",
    )

    assert destination == (
        tmp_path / "sources" / "tenant-a" / "00000000-0000-5000-8000-000000000001" / "source.txt"
    )
