"""Streaming quarantine, immutable sources, and deterministic derived artifacts."""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
from collections.abc import AsyncIterable
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter

from app.domain.errors import InvalidUploadError, UploadTooLargeError
from app.domain.models import Chunk, IndexManifest, ParsedDocument, TenantPrincipal
from app.domain.uploads import StagedUpload


class DocumentFileStorage:
    """Own all runtime paths; caller filenames never influence storage paths."""

    def __init__(self, quarantine_root: Path, source_root: Path) -> None:
        self._quarantine_root = quarantine_root
        self._source_root = source_root

    async def initialize(self) -> None:
        await asyncio.to_thread(self._quarantine_root.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(self._source_root.mkdir, parents=True, exist_ok=True)

    async def stage(
        self,
        principal: TenantPrincipal,
        chunks: AsyncIterable[bytes],
        *,
        max_bytes: int,
    ) -> StagedUpload:
        tenant_root = self._quarantine_root / principal.tenant_id
        await asyncio.to_thread(tenant_root.mkdir, parents=True, exist_ok=True)
        path = tenant_root / f"{uuid4().hex}.part"
        checksum = hashlib.sha256()
        size = 0
        first_bytes = bytearray()
        handle = path.open("xb")
        try:
            async for chunk in chunks:
                if not chunk:
                    continue
                size += len(chunk)
                if size > max_bytes:
                    raise UploadTooLargeError()
                checksum.update(chunk)
                if len(first_bytes) < 4096:
                    first_bytes.extend(chunk[: 4096 - len(first_bytes)])
                await asyncio.to_thread(handle.write, chunk)
            if size == 0:
                raise InvalidUploadError(public_message="The uploaded document is empty.")
            await asyncio.to_thread(handle.flush)
            await asyncio.to_thread(os.fsync, handle.fileno())
        except BaseException:
            handle.close()
            path.unlink(missing_ok=True)
            raise
        finally:
            if not handle.closed:
                handle.close()
        return StagedUpload(
            path=path,
            checksum_sha256=checksum.hexdigest(),
            size_bytes=size,
            first_bytes=bytes(first_bytes),
        )

    async def promote(
        self,
        staged: StagedUpload,
        principal: TenantPrincipal,
        document_id: str,
        source_suffix: str,
    ) -> Path:
        document_root = self.document_root(principal.tenant_id, document_id)
        await asyncio.to_thread(document_root.mkdir, parents=True, exist_ok=True)
        destination = document_root / f"source{source_suffix}"
        if destination.exists():
            await self.discard(staged)
            return destination
        await asyncio.to_thread(os.replace, staged.path, destination)
        return destination

    async def discard(self, staged: StagedUpload) -> None:
        await asyncio.to_thread(staged.path.unlink, missing_ok=True)

    def document_root(self, tenant_id: str, document_id: str) -> Path:
        return self._source_root / tenant_id / document_id

    def source_path(self, tenant_id: str, document_id: str, source_suffix: str) -> Path:
        return self.document_root(tenant_id, document_id) / f"source{source_suffix}"

    async def persist_parsed(self, document: ParsedDocument) -> None:
        await self._write_atomic(
            self.document_root(document.tenant_id, document.document_id) / "elements.json",
            document.model_dump_json(indent=2).encode("utf-8"),
        )

    async def persist_chunks(self, tenant_id: str, document_id: str, chunks: list[Chunk]) -> None:
        payload = TypeAdapter(list[Chunk]).dump_json(chunks, indent=2)
        await self._write_atomic(
            self.document_root(tenant_id, document_id) / "chunks.json",
            payload,
        )

    async def persist_index_manifest(
        self,
        tenant_id: str,
        document_id: str,
        manifest: IndexManifest,
    ) -> None:
        await self._write_atomic(
            self.document_root(tenant_id, document_id) / "index-manifest.json",
            manifest.model_dump_json(indent=2).encode("utf-8"),
        )

    async def delete_document(self, tenant_id: str, document_id: str) -> None:
        root = self.document_root(tenant_id, document_id)
        if root.exists():
            await asyncio.to_thread(shutil.rmtree, root)

    async def _write_atomic(self, destination: Path, payload: bytes) -> None:
        await asyncio.to_thread(destination.parent.mkdir, parents=True, exist_ok=True)
        temporary = destination.with_suffix(f"{destination.suffix}.tmp")

        def write() -> None:
            with temporary.open("wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)

        await asyncio.to_thread(write)
