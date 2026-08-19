"""Internal upload values shared by application and storage adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StagedUpload:
    """Result of a bounded quarantine write."""

    path: Path
    checksum_sha256: str
    size_bytes: int
    first_bytes: bytes
