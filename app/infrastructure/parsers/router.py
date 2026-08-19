"""Select a normalized parser only after upload policy validation."""

from __future__ import annotations

from pathlib import PurePath

from app.domain.errors import UnsupportedMediaTypeError
from app.domain.protocols import Parser
from app.infrastructure.parsers.docling_pdf import DoclingPDFParser
from app.infrastructure.parsers.text import CSVParser, LogParser, MarkdownParser, PlainTextParser


class ParserRouter:
    """Route accepted source suffixes to parser adapters."""

    def __init__(
        self,
        *,
        pdf: DoclingPDFParser,
        text: PlainTextParser,
        markdown: MarkdownParser,
        csv_parser: CSVParser,
        log: LogParser,
    ) -> None:
        self._parsers: dict[str, Parser] = {
            ".pdf": pdf,
            ".txt": text,
            ".md": markdown,
            ".markdown": markdown,
            ".csv": csv_parser,
            ".log": log,
        }

    def parser_for(self, filename: str) -> Parser:
        suffix = PurePath(filename).suffix.lower()
        parser = self._parsers.get(suffix)
        if parser is None:
            raise UnsupportedMediaTypeError()
        return parser
