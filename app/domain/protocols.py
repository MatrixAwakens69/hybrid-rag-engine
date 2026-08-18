"""Project-owned interfaces that isolate domain logic from infrastructure SDKs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.domain.models import (
    Chunk,
    DocumentMetadata,
    DocumentStatus,
    EvidenceItem,
    ParsedDocument,
    TenantPrincipal,
)


@runtime_checkable
class VersionedModelAdapter(Protocol):
    """Common identity required for reproducibility."""

    @property
    def model_id(self) -> str: ...

    @property
    def revision(self) -> str: ...


class Parser(Protocol):
    """Convert an untrusted source into normalized elements."""

    @property
    def version(self) -> str: ...

    async def parse(self, source: Path, *, document_id: str) -> ParsedDocument: ...


class Chunker(Protocol):
    """Create deterministic, source-traceable chunks."""

    @property
    def version(self) -> str: ...

    def chunk(self, document: ParsedDocument) -> Sequence[Chunk]: ...


class DenseEmbedder(VersionedModelAdapter, Protocol):
    """Create dense vectors for documents and queries."""

    @property
    def dimensions(self) -> int: ...

    async def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...

    async def embed_query(self, text: str) -> Sequence[float]: ...


class SparseVector(Protocol):
    """Provider-neutral sparse vector representation."""

    @property
    def indices(self) -> Sequence[int]: ...

    @property
    def values(self) -> Sequence[float]: ...


class SparseEmbedder(VersionedModelAdapter, Protocol):
    """Create sparse representations for documents and queries."""

    async def embed_documents(self, texts: Sequence[str]) -> Sequence[SparseVector]: ...

    async def embed_query(self, text: str) -> SparseVector: ...


class Reranker(VersionedModelAdapter, Protocol):
    """Jointly score a query and bounded evidence candidates."""

    async def rerank(
        self,
        query: str,
        candidates: Sequence[EvidenceItem],
        *,
        top_k: int,
    ) -> Sequence[EvidenceItem]: ...


class Generator(VersionedModelAdapter, Protocol):
    """Generate untrusted structured output from allowed evidence."""

    async def generate(
        self,
        question: str,
        evidence: Sequence[EvidenceItem],
        *,
        prompt_version: str,
    ) -> str: ...


class DocumentRepository(Protocol):
    """Tenant-scoped document lifecycle persistence."""

    async def get(
        self,
        principal: TenantPrincipal,
        document_id: str,
    ) -> DocumentMetadata | None: ...

    async def list(
        self,
        principal: TenantPrincipal,
        *,
        cursor: str | None,
        limit: int,
    ) -> tuple[Sequence[DocumentMetadata], str | None]: ...

    async def upsert(
        self,
        principal: TenantPrincipal,
        document: DocumentMetadata,
    ) -> None: ...

    async def set_status(
        self,
        principal: TenantPrincipal,
        document_id: str,
        status: DocumentStatus,
        *,
        failure_code: str | None = None,
    ) -> None: ...

    async def delete(self, principal: TenantPrincipal, document_id: str) -> None: ...


class RetrievalIndex(Protocol):
    """Tenant-filtered hybrid index."""

    async def search(
        self,
        principal: TenantPrincipal,
        *,
        dense_vector: Sequence[float],
        sparse_vector: SparseVector,
        document_ids: Sequence[str],
        metadata_filters: Mapping[str, str | int | float | bool],
        dense_limit: int,
        sparse_limit: int,
    ) -> Sequence[EvidenceItem]: ...

    async def delete_document(
        self,
        principal: TenantPrincipal,
        document_id: str,
    ) -> None: ...
