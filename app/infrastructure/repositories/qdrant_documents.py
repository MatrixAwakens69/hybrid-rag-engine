"""Tenant-scoped document control records in Qdrant."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from app.domain.models import (
    DocumentRecord,
    DocumentStatus,
    DocumentWarning,
    TenantPrincipal,
    VersionManifest,
)
from app.domain.policies.lifecycle import require_transition


class QdrantDocumentRepository:
    """Persist minimal lifecycle records with mandatory tenant checks."""

    def __init__(self, client: AsyncQdrantClient, collection_name: str) -> None:
        self._client = client
        self._collection_name = collection_name

    async def initialize(self) -> None:
        if not await self._client.collection_exists(self._collection_name):
            try:
                await self._client.create_collection(
                    collection_name=self._collection_name,
                    vectors_config=VectorParams(size=1, distance=Distance.DOT),
                    on_disk_payload=True,
                )
            except Exception:
                if not await self._client.collection_exists(self._collection_name):
                    raise
        for field_name in ("tenant_id", "document.document_id", "document.status"):
            await self._client.create_payload_index(
                collection_name=self._collection_name,
                field_name=field_name,
                field_schema=PayloadSchemaType.KEYWORD,
                wait=True,
            )

    async def get(
        self,
        principal: TenantPrincipal,
        document_id: str,
    ) -> DocumentRecord | None:
        points = await self._client.retrieve(
            collection_name=self._collection_name,
            ids=[document_id],
            with_payload=True,
            with_vectors=False,
        )
        if not points or points[0].payload is None:
            return None
        record = DocumentRecord.model_validate(points[0].payload)
        if record.tenant_id != principal.tenant_id:
            return None
        return record

    async def list(
        self,
        principal: TenantPrincipal,
        *,
        cursor: str | None,
        limit: int,
    ) -> tuple[Sequence[DocumentRecord], str | None]:
        points, next_offset = await self._client.scroll(
            collection_name=self._collection_name,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="tenant_id",
                        match=MatchValue(value=principal.tenant_id),
                    )
                ]
            ),
            offset=cursor,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        records = [
            DocumentRecord.model_validate(point.payload)
            for point in points
            if point.payload is not None
        ]
        return records, str(next_offset) if next_offset is not None else None

    async def upsert(
        self,
        principal: TenantPrincipal,
        document: DocumentRecord,
    ) -> None:
        if document.tenant_id != principal.tenant_id:
            raise ValueError("principal tenant does not match document tenant")
        await self._client.upsert(
            collection_name=self._collection_name,
            points=[
                PointStruct(
                    id=document.document.document_id,
                    vector=[0.0],
                    payload=document.model_dump(mode="json"),
                )
            ],
            wait=True,
        )

    async def set_status(
        self,
        principal: TenantPrincipal,
        document_id: str,
        status: DocumentStatus,
        *,
        failure_code: str | None = None,
        warnings: Sequence[DocumentWarning] | None = None,
        versions: VersionManifest | None = None,
    ) -> None:
        record = await self.get(principal, document_id)
        if record is None:
            return
        require_transition(record.document.status, status)
        metadata = record.document.model_copy(
            update={"status": status, "updated_at": datetime.now(UTC)}
        )
        updated = record.model_copy(
            update={
                "document": metadata,
                "failure_code": failure_code,
                "warnings": list(warnings) if warnings is not None else record.warnings,
                "versions": versions or record.versions,
            }
        )
        await self.upsert(principal, updated)

    async def delete(self, principal: TenantPrincipal, document_id: str) -> None:
        await self.set_status(principal, document_id, DocumentStatus.DELETED)
