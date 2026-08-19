"""Bounded parsers for text, Markdown, CSV, and log sources."""

from __future__ import annotations

import asyncio
import csv
import re
from collections.abc import Sequence
from pathlib import Path

from charset_normalizer import from_bytes

from app.domain.errors import ProcessingError
from app.domain.models import DocumentElement, ParsedDocument
from app.domain.models.ingestion import ElementType
from app.domain.models.query import SourceLocation
from app.domain.policies.ids import element_id

_LOG_START = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}|"
    r"\d{2}:\d{2}:\d{2}|"
    r"\[(?:TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL)\])",
    re.IGNORECASE,
)


class _BoundedTextParser:
    def __init__(self, version: str, *, max_lines: int, max_characters: int) -> None:
        self._version = version
        self._max_lines = max_lines
        self._max_characters = max_characters

    @property
    def version(self) -> str:
        return self._version

    async def _read_lines(self, source: Path) -> tuple[list[str], list[str]]:
        return await asyncio.to_thread(self._read_lines_sync, source)

    def _read_lines_sync(self, source: Path) -> tuple[list[str], list[str]]:
        with source.open("rb") as sample_handle:
            sample = sample_handle.read(64 * 1024)
        warnings: list[str] = []
        encoding = "utf-8"
        try:
            sample.decode("utf-8")
        except UnicodeDecodeError:
            match = from_bytes(sample).best()
            encoding = match.encoding if match and match.encoding else "latin-1"
            warnings.append("encoding_fallback")
        lines: list[str] = []
        with source.open("r", encoding=encoding, errors="replace", newline="") as handle:
            for line_number, line in enumerate(handle, start=1):
                if line_number > self._max_lines:
                    raise ProcessingError(public_message="The document exceeds the line limit.")
                lines.append(line.rstrip("\r\n"))
        return lines, warnings

    def _element(
        self,
        *,
        document_id: str,
        ordinal: int,
        element_type: ElementType,
        text: str,
        line_start: int,
        line_end: int,
        hierarchy_path: Sequence[str] = (),
    ) -> DocumentElement:
        bounded = text[: self._max_characters]
        return DocumentElement(
            element_id=element_id(document_id, ordinal, bounded),
            element_type=element_type,
            text=bounded,
            ordinal=ordinal,
            location=SourceLocation(
                line_start=line_start,
                line_end=line_end,
                hierarchy_path=list(hierarchy_path),
            ),
        )

    def _parsed(
        self,
        *,
        document_id: str,
        document_version_id: str,
        tenant_id: str,
        checksum_sha256: str,
        elements: list[DocumentElement],
        warnings: list[str],
    ) -> ParsedDocument:
        if not elements:
            raise ProcessingError(public_message="The document contains no parseable text.")
        return ParsedDocument(
            document_id=document_id,
            document_version_id=document_version_id,
            tenant_id=tenant_id,
            checksum_sha256=checksum_sha256,
            elements=elements,
            warning_codes=warnings,
            parser_version=self.version,
        )


class PlainTextParser(_BoundedTextParser):
    async def parse(
        self,
        source: Path,
        *,
        document_id: str,
        document_version_id: str,
        tenant_id: str,
        checksum_sha256: str,
    ) -> ParsedDocument:
        lines, warnings = await self._read_lines(source)
        elements: list[DocumentElement] = []
        paragraph: list[str] = []
        start = 1
        for line_number, line in enumerate([*lines, ""], start=1):
            if line.strip():
                if not paragraph:
                    start = line_number
                paragraph.append(line)
                continue
            if paragraph:
                text = "\n".join(paragraph)
                elements.append(
                    self._element(
                        document_id=document_id,
                        ordinal=len(elements),
                        element_type=ElementType.PARAGRAPH,
                        text=text,
                        line_start=start,
                        line_end=line_number - 1,
                    )
                )
                paragraph.clear()
        return self._parsed(
            document_id=document_id,
            document_version_id=document_version_id,
            tenant_id=tenant_id,
            checksum_sha256=checksum_sha256,
            elements=elements,
            warnings=warnings,
        )


class MarkdownParser(_BoundedTextParser):
    async def parse(
        self,
        source: Path,
        *,
        document_id: str,
        document_version_id: str,
        tenant_id: str,
        checksum_sha256: str,
    ) -> ParsedDocument:
        lines, warnings = await self._read_lines(source)
        elements: list[DocumentElement] = []
        hierarchy: list[str] = []
        buffer: list[str] = []
        buffer_start = 1
        in_code = False

        def flush(end_line: int, element_type: ElementType = ElementType.PARAGRAPH) -> None:
            nonlocal buffer
            if not buffer:
                return
            elements.append(
                self._element(
                    document_id=document_id,
                    ordinal=len(elements),
                    element_type=element_type,
                    text="\n".join(buffer),
                    line_start=buffer_start,
                    line_end=end_line,
                    hierarchy_path=hierarchy,
                )
            )
            buffer = []

        for line_number, line in enumerate(lines, start=1):
            if line.startswith("```"):
                if in_code:
                    buffer.append(line)
                    flush(line_number, ElementType.CODE)
                    in_code = False
                else:
                    flush(line_number - 1)
                    in_code = True
                    buffer_start = line_number
                    buffer.append(line)
                continue
            if in_code:
                buffer.append(line)
                continue
            heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
            if heading:
                flush(line_number - 1)
                level = len(heading.group(1))
                text = heading.group(2)
                hierarchy = hierarchy[: level - 1]
                hierarchy.append(text)
                elements.append(
                    self._element(
                        document_id=document_id,
                        ordinal=len(elements),
                        element_type=ElementType.HEADING,
                        text=text,
                        line_start=line_number,
                        line_end=line_number,
                        hierarchy_path=hierarchy,
                    )
                )
            elif line.strip():
                if not buffer:
                    buffer_start = line_number
                buffer.append(line)
            else:
                flush(line_number - 1)
        flush(len(lines), ElementType.CODE if in_code else ElementType.PARAGRAPH)
        if in_code:
            warnings.append("unclosed_code_fence")
        return self._parsed(
            document_id=document_id,
            document_version_id=document_version_id,
            tenant_id=tenant_id,
            checksum_sha256=checksum_sha256,
            elements=elements,
            warnings=warnings,
        )


class CSVParser(_BoundedTextParser):
    def __init__(
        self,
        version: str,
        *,
        max_lines: int,
        max_characters: int,
        max_rows: int,
        max_columns: int,
    ) -> None:
        super().__init__(version, max_lines=max_lines, max_characters=max_characters)
        self._max_rows = max_rows
        self._max_columns = max_columns

    async def parse(
        self,
        source: Path,
        *,
        document_id: str,
        document_version_id: str,
        tenant_id: str,
        checksum_sha256: str,
    ) -> ParsedDocument:
        lines, warnings = await self._read_lines(source)
        rows = list(csv.reader(lines))
        if len(rows) > self._max_rows:
            raise ProcessingError(public_message="The CSV exceeds the row limit.")
        if not rows:
            raise ProcessingError(public_message="The CSV is empty.")
        width = len(rows[0])
        if width > self._max_columns:
            raise ProcessingError(public_message="The CSV exceeds the column limit.")
        elements: list[DocumentElement] = []
        for row_number, row in enumerate(rows, start=1):
            if len(row) > self._max_columns:
                raise ProcessingError(public_message="The CSV exceeds the column limit.")
            if len(row) != width:
                warnings.append("ragged_csv_row")
            text = " | ".join(row)
            elements.append(
                self._element(
                    document_id=document_id,
                    ordinal=len(elements),
                    element_type=ElementType.TABLE_ROW,
                    text=text,
                    line_start=row_number,
                    line_end=row_number,
                    hierarchy_path=["CSV"],
                )
            )
        return self._parsed(
            document_id=document_id,
            document_version_id=document_version_id,
            tenant_id=tenant_id,
            checksum_sha256=checksum_sha256,
            elements=elements,
            warnings=list(dict.fromkeys(warnings)),
        )


class LogParser(_BoundedTextParser):
    async def parse(
        self,
        source: Path,
        *,
        document_id: str,
        document_version_id: str,
        tenant_id: str,
        checksum_sha256: str,
    ) -> ParsedDocument:
        lines, warnings = await self._read_lines(source)
        records: list[tuple[int, int, str]] = []
        buffer: list[str] = []
        start = 1
        for line_number, line in enumerate(lines, start=1):
            if _LOG_START.match(line) and buffer:
                records.append((start, line_number - 1, "\n".join(buffer)))
                buffer = []
                start = line_number
            elif not buffer:
                start = line_number
                if line.strip() and not _LOG_START.match(line):
                    warnings.append("unstructured_log_record")
            if line.strip():
                buffer.append(line)
        if buffer:
            records.append((start, len(lines), "\n".join(buffer)))
        elements = [
            self._element(
                document_id=document_id,
                ordinal=ordinal,
                element_type=ElementType.LOG_RECORD,
                text=text,
                line_start=line_start,
                line_end=line_end,
            )
            for ordinal, (line_start, line_end, text) in enumerate(records)
        ]
        return self._parsed(
            document_id=document_id,
            document_version_id=document_version_id,
            tenant_id=tenant_id,
            checksum_sha256=checksum_sha256,
            elements=elements,
            warnings=list(dict.fromkeys(warnings)),
        )
