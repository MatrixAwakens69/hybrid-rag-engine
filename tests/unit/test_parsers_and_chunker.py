"""Golden normalized parsing and structure-aware chunking behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.errors import ProcessingError
from app.domain.models.ingestion import ElementType
from app.infrastructure.chunking.structure_aware import StructureAwareChunker
from app.infrastructure.parsers.docling_pdf import DoclingPDFParser
from app.infrastructure.parsers.text import CSVParser, LogParser, MarkdownParser, PlainTextParser

_CONTEXT = {
    "document_id": "00000000-0000-5000-8000-000000000010",
    "document_version_id": "00000000-0000-5000-8000-000000000010",
    "tenant_id": "tenant-a",
    "checksum_sha256": "a" * 64,
}


@pytest.mark.asyncio
async def test_markdown_preserves_heading_and_code_structure(tmp_path: Path) -> None:
    source = tmp_path / "guide.md"
    source.write_text("# Install\n\nRun this.\n\n```bash\nuv sync\n```\n", encoding="utf-8")
    parser = MarkdownParser("parser-v1", max_lines=100, max_characters=10_000)

    parsed = await parser.parse(source, **_CONTEXT)

    assert [item.element_type for item in parsed.elements] == [
        ElementType.HEADING,
        ElementType.PARAGRAPH,
        ElementType.CODE,
    ]
    assert parsed.elements[1].location.hierarchy_path == ["Install"]
    assert parsed.elements[2].location.line_start == 5


@pytest.mark.asyncio
async def test_csv_records_ragged_rows_and_row_spans(tmp_path: Path) -> None:
    source = tmp_path / "data.csv"
    source.write_text("name,value\nalpha,1\nbeta\n", encoding="utf-8")
    parser = CSVParser(
        "parser-v1",
        max_lines=100,
        max_characters=10_000,
        max_rows=100,
        max_columns=10,
    )

    parsed = await parser.parse(source, **_CONTEXT)

    assert "ragged_csv_row" in parsed.warning_codes
    assert parsed.elements[1].location.line_start == 2
    assert parsed.elements[1].element_type is ElementType.TABLE_ROW


@pytest.mark.asyncio
async def test_log_parser_keeps_independent_records(tmp_path: Path) -> None:
    source = tmp_path / "service.log"
    source.write_text(
        "2026-08-19 10:00:00 INFO started\ncontinuation\n2026-08-19 10:00:01 ERROR failed\n",
        encoding="utf-8",
    )
    parser = LogParser("parser-v1", max_lines=100, max_characters=10_000)

    parsed = await parser.parse(source, **_CONTEXT)

    assert len(parsed.elements) == 2
    assert parsed.elements[0].location.line_start == 1
    assert parsed.elements[0].location.line_end == 2
    assert parsed.elements[1].location.line_start == 3


@pytest.mark.asyncio
async def test_chunker_is_stable_bounded_and_traceable(tmp_path: Path) -> None:
    source = tmp_path / "long.txt"
    source.write_text(("grounded evidence " * 300) + "\n", encoding="utf-8")
    parser = PlainTextParser("parser-v1", max_lines=100, max_characters=100_000)
    parsed = await parser.parse(source, **_CONTEXT)
    chunker = StructureAwareChunker(
        "chunk-v1",
        target_tokens=40,
        max_tokens=50,
        overlap_tokens=5,
    )

    first = list(chunker.chunk(parsed))
    repeated = list(chunker.chunk(parsed))

    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in repeated]
    assert all(chunk.token_count <= 50 for chunk in first)
    assert all(chunk.tenant_id == "tenant-a" for chunk in first)
    assert all(chunk.checksum_sha256 == "a" * 64 for chunk in first)
    assert all(chunk.location.line_start == 1 for chunk in first)


@pytest.mark.asyncio
async def test_docling_adapter_maps_corrupt_pdf_to_safe_failure(tmp_path: Path) -> None:
    source = tmp_path / "corrupt.pdf"
    source.write_bytes(b"%PDF-corrupt")
    parser = DoclingPDFParser(
        "parser-v1",
        max_pages=10,
        max_characters=10_000,
        timeout_seconds=10,
    )

    with pytest.raises(ProcessingError, match="corrupt, encrypted, or unsupported"):
        await parser.parse(source, **_CONTEXT)


@pytest.mark.asyncio
async def test_chunker_repeats_table_header_and_does_not_overlap_logs(tmp_path: Path) -> None:
    csv_source = tmp_path / "wide.csv"
    csv_source.write_text(
        "name,value\n" + "\n".join(f"row-{index},{'x' * 30}" for index in range(8)),
        encoding="utf-8",
    )
    csv_parser = CSVParser(
        "parser-v1",
        max_lines=100,
        max_characters=10_000,
        max_rows=100,
        max_columns=10,
    )
    parsed_csv = await csv_parser.parse(csv_source, **_CONTEXT)
    chunker = StructureAwareChunker(
        "chunk-v1",
        target_tokens=25,
        max_tokens=40,
        overlap_tokens=5,
    )
    table_chunks = list(chunker.chunk(parsed_csv))

    assert len(table_chunks) > 1
    assert all("name | value" in chunk.text for chunk in table_chunks)

    log_source = tmp_path / "records.log"
    log_source.write_text(
        "2026-08-19 10:00:00 INFO first unique-record\n"
        "2026-08-19 10:00:01 ERROR second unique-record\n",
        encoding="utf-8",
    )
    parsed_log = await LogParser(
        "parser-v1",
        max_lines=100,
        max_characters=10_000,
    ).parse(log_source, **_CONTEXT)
    log_chunks = list(chunker.chunk(parsed_log))

    assert len(log_chunks) == 2
    assert "second unique-record" not in log_chunks[0].text
    assert "first unique-record" not in log_chunks[1].text


@pytest.mark.asyncio
async def test_chunker_attaches_heading_context_to_prose(tmp_path: Path) -> None:
    source = tmp_path / "headed.md"
    source.write_text("# Security\n\nTenant filters are mandatory.\n", encoding="utf-8")
    parsed = await MarkdownParser(
        "parser-v1",
        max_lines=100,
        max_characters=10_000,
    ).parse(source, **_CONTEXT)
    chunker = StructureAwareChunker(
        "chunk-v1",
        target_tokens=40,
        max_tokens=60,
        overlap_tokens=5,
    )

    chunks = list(chunker.chunk(parsed))

    assert len(chunks) == 1
    assert chunks[0].text.startswith("# Security")
    assert chunks[0].hierarchy_path == ["Security"]
