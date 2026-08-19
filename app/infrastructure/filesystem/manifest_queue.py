"""Single-worker durable queue using fsynced JSON and atomic renames."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path

from app.domain.errors import ManifestConflictError
from app.domain.models import IngestionJobState
from app.domain.models.ingestion import JobClaimState


class ManifestQueue:
    """At-least-once filesystem queue for one worker per deployment."""

    _STATE_DIRECTORIES = ("pending", "processing", "completed", "failed")

    def __init__(self, root: Path) -> None:
        self._root = root

    async def initialize(self) -> None:
        for state in self._STATE_DIRECTORIES:
            await asyncio.to_thread((self._root / state).mkdir, parents=True, exist_ok=True)

    async def publish(
        self,
        job: IngestionJobState,
        *,
        replace_completed: bool = False,
    ) -> None:
        existing = await self._find(job.job_id)
        if existing is not None:
            existing_path, existing_job = existing
            if existing_job.document_id != job.document_id:
                raise ManifestConflictError()
            if existing_path.parent.name in {"pending", "processing"}:
                return
            if existing_path.parent.name == "completed" and not replace_completed:
                return
            await asyncio.to_thread(existing_path.unlink, missing_ok=True)
        pending = job.model_copy(
            update={
                "claim_state": JobClaimState.PENDING,
                "updated_at": datetime.now(UTC),
                "failure_code": None,
            }
        )
        await self._write_atomic(self._path("pending", job.job_id), pending)

    async def claim_next(self) -> IngestionJobState | None:
        pending_paths = await asyncio.to_thread(
            lambda: sorted((self._root / "pending").glob("*.json"))
        )
        for pending_path in pending_paths:
            processing_path = self._path("processing", pending_path.stem)
            try:
                await asyncio.to_thread(os.replace, pending_path, processing_path)
            except FileNotFoundError:
                continue
            job = await self._read(processing_path)
            claimed = job.model_copy(
                update={
                    "claim_state": JobClaimState.PROCESSING,
                    "updated_at": datetime.now(UTC),
                }
            )
            await self._write_atomic(processing_path, claimed)
            return claimed
        return None

    async def complete(self, job: IngestionJobState) -> None:
        completed = job.model_copy(
            update={
                "claim_state": JobClaimState.COMPLETED,
                "updated_at": datetime.now(UTC),
                "failure_code": None,
            }
        )
        await self._finish("completed", completed)

    async def fail(self, job: IngestionJobState, failure_code: str) -> None:
        failed = job.model_copy(
            update={
                "claim_state": JobClaimState.FAILED,
                "updated_at": datetime.now(UTC),
                "failure_code": failure_code,
            }
        )
        await self._finish("failed", failed)

    async def recover_stale(self, stale_seconds: int) -> int:
        now = datetime.now(UTC)
        recovered = 0
        paths = await asyncio.to_thread(lambda: list((self._root / "processing").glob("*.json")))
        for path in paths:
            job = await self._read(path)
            age = (now - job.updated_at).total_seconds()
            if age < stale_seconds:
                continue
            pending = job.model_copy(
                update={
                    "claim_state": JobClaimState.PENDING,
                    "retry_count": job.retry_count + 1,
                    "updated_at": now,
                }
            )
            await self._write_atomic(self._path("pending", job.job_id), pending)
            await asyncio.to_thread(path.unlink, missing_ok=True)
            recovered += 1
        return recovered

    async def remove_for_document(self, document_id: str, *, skip_job_id: str) -> None:
        for state in self._STATE_DIRECTORIES:
            state_root = self._root / state
            paths = await asyncio.to_thread(list, state_root.glob("*.json"))
            for path in paths:
                if path.stem == skip_job_id:
                    continue
                job = await self._read(path)
                if job.document_id == document_id:
                    await asyncio.to_thread(path.unlink, missing_ok=True)

    async def _finish(self, state: str, job: IngestionJobState) -> None:
        destination = self._path(state, job.job_id)
        await self._write_atomic(destination, job)
        await asyncio.to_thread(
            self._path("processing", job.job_id).unlink,
            missing_ok=True,
        )

    async def _find(self, job_id: str) -> tuple[Path, IngestionJobState] | None:
        for state in self._STATE_DIRECTORIES:
            path = self._path(state, job_id)
            if path.exists():
                return path, await self._read(path)
        return None

    def _path(self, state: str, job_id: str) -> Path:
        return self._root / state / f"{job_id}.json"

    async def _read(self, path: Path) -> IngestionJobState:
        payload = await asyncio.to_thread(path.read_text, encoding="utf-8")
        return IngestionJobState.model_validate_json(payload)

    async def _write_atomic(self, destination: Path, job: IngestionJobState) -> None:
        temporary = destination.with_suffix(".json.tmp")
        payload = job.model_dump_json(indent=2).encode("utf-8")

        def write() -> None:
            with temporary.open("wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)

        await asyncio.to_thread(write)
