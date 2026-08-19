"""Deterministic token-bounded chunking that preserves source structure."""

from __future__ import annotations

from collections.abc import Sequence

import tiktoken

from app.domain.models import Chunk, DocumentElement, ParsedDocument
from app.domain.models.ingestion import ElementType
from app.domain.models.query import SourceLocation
from app.domain.policies.ids import chunk_id


class StructureAwareChunker:
    """Chunk normalized elements without model calls or nondeterministic boundaries."""

    def __init__(
        self,
        version: str,
        *,
        target_tokens: int,
        max_tokens: int,
        overlap_tokens: int,
    ) -> None:
        self._version = version
        self._target_tokens = target_tokens
        self._max_tokens = max_tokens
        self._overlap_tokens = overlap_tokens
        self._encoding = tiktoken.get_encoding("cl100k_base")

    @property
    def version(self) -> str:
        return self._version

    def chunk(self, document: ParsedDocument) -> Sequence[Chunk]:
        chunks: list[Chunk] = []
        elements = sorted(document.elements, key=lambda item: item.ordinal)
        prose_buffer: list[DocumentElement] = []
        index = 0

        def flush_prose() -> None:
            nonlocal prose_buffer
            if prose_buffer:
                self._append_element_group(document, prose_buffer, chunks, overlap=True)
                prose_buffer = []

        while index < len(elements):
            element = elements[index]
            if element.element_type is ElementType.HEADING:
                flush_prose()
                index += 1
                continue
            if element.element_type is ElementType.LOG_RECORD:
                flush_prose()
                self._append_element_group(document, [element], chunks, overlap=False)
                index += 1
                continue
            if element.element_type is ElementType.TABLE_ROW:
                flush_prose()
                table_elements: list[DocumentElement] = []
                hierarchy = element.location.hierarchy_path
                while index < len(elements):
                    candidate = elements[index]
                    if (
                        candidate.element_type is not ElementType.TABLE_ROW
                        or candidate.location.hierarchy_path != hierarchy
                    ):
                        break
                    table_elements.append(candidate)
                    index += 1
                self._append_table(document, table_elements, chunks)
                continue
            candidate_text = self._group_text([*prose_buffer, element])
            if prose_buffer and self._token_count(candidate_text) > self._target_tokens:
                flush_prose()
            prose_buffer.append(element)
            index += 1
        flush_prose()
        return chunks

    def _append_table(
        self,
        document: ParsedDocument,
        elements: list[DocumentElement],
        chunks: list[Chunk],
    ) -> None:
        if not elements:
            return
        header = elements[0]
        group: list[DocumentElement] = [header]
        for row in elements[1:]:
            candidate = [*group, row]
            exceeds_target = self._token_count(self._group_text(candidate)) > self._target_tokens
            if len(group) > 1 and exceeds_target:
                self._append_element_group(document, group, chunks, overlap=False)
                group = [header, row]
            else:
                group.append(row)
        if group:
            self._append_element_group(document, group, chunks, overlap=False)

    def _append_element_group(
        self,
        document: ParsedDocument,
        elements: list[DocumentElement],
        chunks: list[Chunk],
        *,
        overlap: bool,
    ) -> None:
        text = self._group_text(elements)
        tokens = self._encoding.encode(text)
        step = self._max_tokens
        if overlap and len(tokens) > self._max_tokens:
            step = self._max_tokens - self._overlap_tokens
        for start in range(0, len(tokens), step):
            token_slice = tokens[start : start + self._max_tokens]
            if not token_slice:
                continue
            chunk_text = self._encoding.decode(token_slice).strip()
            if not chunk_text:
                continue
            location = self._merge_location(elements)
            ordinal = len(chunks)
            source_span = location.model_dump_json()
            chunks.append(
                Chunk(
                    chunk_id=chunk_id(
                        document.document_version_id,
                        location.hierarchy_path,
                        source_span,
                        ordinal,
                    ),
                    document_id=document.document_id,
                    document_version_id=document.document_version_id,
                    tenant_id=document.tenant_id,
                    checksum_sha256=document.checksum_sha256,
                    text=chunk_text,
                    ordinal=ordinal,
                    location=location,
                    hierarchy_path=location.hierarchy_path,
                    token_count=len(token_slice),
                    parser_version=document.parser_version,
                    chunker_version=self.version,
                )
            )
            if start + self._max_tokens >= len(tokens):
                break

    @staticmethod
    def _group_text(elements: Sequence[DocumentElement]) -> str:
        if not elements:
            return ""
        hierarchy = elements[0].location.hierarchy_path
        heading_context = "\n".join(f"# {heading}" for heading in hierarchy)
        body = "\n\n".join(element.text for element in elements)
        return f"{heading_context}\n\n{body}".strip()

    @staticmethod
    def _merge_location(elements: Sequence[DocumentElement]) -> SourceLocation:
        def minimum(name: str) -> int | None:
            values = [getattr(element.location, name) for element in elements]
            present = [value for value in values if value is not None]
            return min(present) if present else None

        def maximum(name: str) -> int | None:
            values = [getattr(element.location, name) for element in elements]
            present = [value for value in values if value is not None]
            return max(present) if present else None

        return SourceLocation(
            page_start=minimum("page_start"),
            page_end=maximum("page_end"),
            line_start=minimum("line_start"),
            line_end=maximum("line_end"),
            row_start=minimum("row_start"),
            row_end=maximum("row_end"),
            bounding_box=elements[0].location.bounding_box if len(elements) == 1 else None,
            hierarchy_path=list(elements[0].location.hierarchy_path),
        )

    def _token_count(self, text: str) -> int:
        return len(self._encoding.encode(text))
