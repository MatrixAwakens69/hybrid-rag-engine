"""Durable manifest queue atomicity and redelivery behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.domain.models import IngestionJobState, JobOperation
from app.domain.models.ingestion import JobClaimState
from app.infrastructure.filesystem.manifest_queue import ManifestQueue


def _job() -> IngestionJobState:
    now = datetime.now(UTC)
    return IngestionJobState(
        job_id="00000000-0000-5000-8000-000000000001",
        document_id="00000000-0000-5000-8000-000000000002",
        document_version_id="00000000-0000-5000-8000-000000000002",
        tenant_id="tenant-a",
        operation=JobOperation.INGEST,
        claim_state=JobClaimState.PENDING,
        stage="accepted",
        checksum_sha256="a" * 64,
        filename="notes.txt",
        content_type="text/plain",
        source_suffix=".txt",
        parser_version="parser-v1",
        chunker_version="chunk-v1",
        index_schema_version="v1",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_manifest_publish_claim_complete_and_force_requeue(tmp_path: Path) -> None:
    queue = ManifestQueue(tmp_path / "jobs")
    await queue.initialize()
    job = _job()

    await queue.publish(job)
    claimed = await queue.claim_next()

    assert claimed is not None
    assert claimed.claim_state is JobClaimState.PROCESSING
    assert not list((tmp_path / "jobs" / "pending").glob("*.tmp"))

    await queue.complete(claimed)
    assert await queue.claim_next() is None

    await queue.publish(job)
    assert await queue.claim_next() is None

    await queue.publish(job, replace_completed=True)
    replayed = await queue.claim_next()
    assert replayed is not None
    assert replayed.job_id == job.job_id


@pytest.mark.asyncio
async def test_failed_job_can_be_republished(tmp_path: Path) -> None:
    queue = ManifestQueue(tmp_path / "jobs")
    await queue.initialize()
    await queue.publish(_job())
    claimed = await queue.claim_next()
    assert claimed is not None
    await queue.fail(claimed, "processing_failed")

    await queue.publish(_job())

    assert await queue.claim_next() is not None


@pytest.mark.asyncio
async def test_stale_processing_job_is_recovered_for_redelivery(tmp_path: Path) -> None:
    queue = ManifestQueue(tmp_path / "jobs")
    await queue.initialize()
    await queue.publish(_job())
    claimed = await queue.claim_next()
    assert claimed is not None
    stale = claimed.model_copy(update={"updated_at": datetime.now(UTC) - timedelta(hours=1)})
    processing_path = tmp_path / "jobs" / "processing" / f"{claimed.job_id}.json"
    processing_path.write_text(stale.model_dump_json(), encoding="utf-8")

    recovered = await queue.recover_stale(30)
    replayed = await queue.claim_next()

    assert recovered == 1
    assert replayed is not None
    assert replayed.retry_count == 1
