"""Lazy Docling adapter for layout-aware PDF and table extraction."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from app.domain.errors import ProcessingError
from app.domain.models import DocumentElement, ParsedDocument
from app.domain.models.ingestion import ElementType
from app.domain.models.query import SourceLocation
from app.domain.policies.ids import element_id


class DoclingPDFParser:
    """Keep Docling and model imports out of the API process."""

    def __init__(
        self,
        version: str,
        *,
        max_pages: int,
        max_characters: int,
        timeout_seconds: float,
    ) -> None:
        self._version = version
        self._max_pages = max_pages
        self._max_characters = max_characters
        self._timeout_seconds = timeout_seconds

    @property
    def version(self) -> str:
        return self._version

    async def parse(
        self,
        source: Path,
        *,
        document_id: str,
        document_version_id: str,
        tenant_id: str,
        checksum_sha256: str,
    ) -> ParsedDocument:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    self._parse_sync,
                    source,
                    document_id,
                    document_version_id,
                    tenant_id,
                    checksum_sha256,
                ),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as exc:
            raise ProcessingError(public_message="PDF parsing exceeded the time limit.") from exc

    def _parse_sync(
        self,
        source: Path,
        document_id: str,
        document_version_id: str,
        tenant_id: str,
        checksum_sha256: str,
    ) -> ParsedDocument:
        try:
            with source.open("rb") as handle:
                handle.seek(max(source.stat().st_size - 2048, 0))
                if b"%%EOF" not in handle.read():
                    raise ProcessingError(
                        public_message="The PDF is corrupt, encrypted, or unsupported."
                    )
            import pypdfium2 as pdfium
            from docling.document_converter import DocumentConverter

            pdf = pdfium.PdfDocument(source)
            page_count = len(pdf)
            pdf.close()
            if page_count > self._max_pages:
                raise ProcessingError(public_message="The PDF exceeds the page limit.")
            result = DocumentConverter().convert(source)
        except ProcessingError:
            raise
        except Exception as exc:
            raise ProcessingError(
                public_message="The PDF is corrupt, encrypted, or unsupported."
            ) from exc

        elements: list[DocumentElement] = []
        hierarchy: list[str] = []
        for item, level in result.document.iterate_items():
            item_any: Any = item
            label_value = getattr(item_any, "label", "")
            label = getattr(label_value, "value", str(label_value)).lower()
            if "section_header" in label or label == "title":
                text = str(getattr(item, "text", "")).strip()
                if not text:
                    continue
                hierarchy = hierarchy[: max(level - 1, 0)]
                hierarchy.append(text)
                elements.append(
                    self._element(
                        document_id,
                        len(elements),
                        ElementType.HEADING,
                        text,
                        item,
                        hierarchy,
                    )
                )
                continue
            if "table" in label:
                elements.extend(
                    self._table_elements(
                        document_id,
                        len(elements),
                        item,
                        result.document,
                        hierarchy,
                    )
                )
                continue
            text = str(getattr(item, "text", "")).strip()
            if not text:
                continue
            elements.append(
                self._element(
                    document_id,
                    len(elements),
                    ElementType.PARAGRAPH,
                    text,
                    item,
                    hierarchy,
                )
            )
        if not elements:
            raise ProcessingError(public_message="The PDF contains no parseable text.")
        return ParsedDocument(
            document_id=document_id,
            document_version_id=document_version_id,
            tenant_id=tenant_id,
            checksum_sha256=checksum_sha256,
            elements=elements,
            warning_codes=[],
            parser_version=self.version,
        )

    def _table_elements(
        self,
        document_id: str,
        start_ordinal: int,
        item: Any,
        document: Any,
        hierarchy: list[str],
    ) -> list[DocumentElement]:
        try:
            dataframe = item.export_to_dataframe(doc=document)
            headers = [str(column) for column in dataframe.columns]
            elements: list[DocumentElement] = []
            for row_offset, row in enumerate(
                dataframe.itertuples(index=False, name=None),
                start=1,
            ):
                values = [str(value) for value in row]
                text = " | ".join(
                    f"{header}: {value}" for header, value in zip(headers, values, strict=True)
                )
                location = self._location(item, hierarchy)
                location = location.model_copy(
                    update={"row_start": row_offset, "row_end": row_offset}
                )
                ordinal = start_ordinal + len(elements)
                bounded = text[: self._max_characters]
                elements.append(
                    DocumentElement(
                        element_id=element_id(document_id, ordinal, bounded),
                        element_type=ElementType.TABLE_ROW,
                        text=bounded,
                        ordinal=ordinal,
                        location=location,
                    )
                )
            return elements
        except Exception as exc:
            raise ProcessingError(public_message="A PDF table could not be normalized.") from exc

    def _element(
        self,
        document_id: str,
        ordinal: int,
        element_type: ElementType,
        text: str,
        item: Any,
        hierarchy: list[str],
    ) -> DocumentElement:
        bounded = text[: self._max_characters]
        return DocumentElement(
            element_id=element_id(document_id, ordinal, bounded),
            element_type=element_type,
            text=bounded,
            ordinal=ordinal,
            location=self._location(item, hierarchy),
        )

    @staticmethod
    def _location(item: Any, hierarchy: list[str]) -> SourceLocation:
        provenance = getattr(item, "prov", None) or []
        if not provenance:
            return SourceLocation(hierarchy_path=list(hierarchy))
        first = provenance[0]
        bbox = getattr(first, "bbox", None)
        bounding_box = None
        if bbox is not None:
            bounding_box = (
                float(bbox.l),
                float(bbox.t),
                float(bbox.r),
                float(bbox.b),
            )
        page = int(first.page_no)
        return SourceLocation(
            page_start=page,
            page_end=page,
            bounding_box=bounding_box,
            hierarchy_path=list(hierarchy),
        )
