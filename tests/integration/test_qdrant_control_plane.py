"""Qdrant-backed authentication and tenant-scoped document records."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from qdrant_client import AsyncQdrantClient

from app.domain.errors import UnauthorizedError
from app.domain.models import (
    DocumentMetadata,
    DocumentRecord,
    DocumentStatus,
    TenantPrincipal,
    VersionManifest,
)
from app.infrastructure.auth.qdrant_api_keys import QdrantAPIKeyAuthenticator
from app.infrastructure.repositories.qdrant_documents import QdrantDocumentRepository


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.filterwarnings("ignore:Payload indexes have no effect in the local Qdrant:UserWarning")
async def test_api_key_hashes_and_tenant_document_filters() -> None:
    client = AsyncQdrantClient(location=":memory:")
    authenticator = QdrantAPIKeyAuthenticator(
        client,
        "test_api_keys",
        bootstrap_key_id="bootstrap",
    )
    repository = QdrantDocumentRepository(client, "test_documents")
    await authenticator.initialize()
    await repository.initialize()
    await authenticator.seed_key(
        key_id="bootstrap",
        tenant_id="tenant-a",
        raw_secret="a-strong-test-secret",
        scopes=frozenset({"documents:read"}),
    )

    principal = await authenticator.authenticate("a-strong-test-secret")
    assert principal.tenant_id == "tenant-a"
    with pytest.raises(UnauthorizedError):
        await authenticator.authenticate("wrong")
    await authenticator.seed_key(
        key_id="tenant-b-key",
        tenant_id="tenant-b",
        raw_secret="first-secret",
        scopes=frozenset({"documents:read"}),
    )
    assert (await authenticator.authenticate("tenant-b-key.first-secret")).tenant_id == "tenant-b"
    await authenticator.seed_key(
        key_id="tenant-b-key",
        tenant_id="tenant-b",
        raw_secret="rotated-secret",
        scopes=frozenset({"documents:read"}),
    )
    with pytest.raises(UnauthorizedError):
        await authenticator.authenticate("tenant-b-key.first-secret")
    assert (await authenticator.authenticate("tenant-b-key.rotated-secret")).tenant_id == "tenant-b"

    document_id = "00000000-0000-5000-8000-000000000099"
    now = datetime.now(UTC)
    record = DocumentRecord(
        tenant_id="tenant-a",
        document=DocumentMetadata(
            document_id=document_id,
            filename="notes.txt",
            content_type="text/plain",
            checksum_sha256="a" * 64,
            status=DocumentStatus.ACCEPTED,
            created_at=now,
            updated_at=now,
        ),
        versions=VersionManifest(app_revision="test", index_schema_version="v1"),
    )
    await repository.upsert(principal, record)

    other_tenant = TenantPrincipal(tenant_id="tenant-b", key_id="key-b")
    assert await repository.get(principal, document_id) is not None
    assert await repository.get(other_tenant, document_id) is None
    own_records, _ = await repository.list(principal, cursor=None, limit=10)
    other_records, _ = await repository.list(other_tenant, cursor=None, limit=10)
    assert len(own_records) == 1
    assert not other_records

    await repository.set_status(principal, document_id, DocumentStatus.PARSING)
    updated = await repository.get(principal, document_id)
    assert updated is not None
    assert updated.document.status is DocumentStatus.PARSING
    await repository.set_status(principal, document_id, DocumentStatus.DELETING)
    await repository.delete(principal, document_id)
    deleted = await repository.get(principal, document_id)
    assert deleted is not None
    assert deleted.document.status is DocumentStatus.DELETED

    await client.close()
