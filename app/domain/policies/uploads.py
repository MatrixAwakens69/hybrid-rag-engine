"""Pure upload validation and filename-sanitization policies."""

from __future__ import annotations

import json
import re
from pathlib import PurePath

from app.domain.errors import InvalidUploadError, UnsupportedMediaTypeError
from app.domain.models.documents import MetadataValue

SUPPORTED_MEDIA_TYPES: dict[str, frozenset[str]] = {
    ".pdf": frozenset({"application/pdf"}),
    ".csv": frozenset({"text/csv", "application/csv"}),
    ".md": frozenset({"text/markdown", "text/plain"}),
    ".markdown": frozenset({"text/markdown", "text/plain"}),
    ".txt": frozenset({"text/plain"}),
    ".log": frozenset({"text/plain", "text/x-log", "application/log"}),
}
_SAFE_FILENAME_CHARACTER = re.compile(r"[^A-Za-z0-9._ -]+")


def sanitize_filename(filename: str) -> str:
    """Return bounded display metadata; never use this value as a storage path."""

    normalized = filename.replace("\\", "/")
    basename = PurePath(normalized).name
    cleaned = _SAFE_FILENAME_CHARACTER.sub("_", basename).strip(" .")
    if not cleaned:
        cleaned = "document"
    return cleaned[:255]


def validate_upload_type(filename: str, content_type: str, first_bytes: bytes) -> str:
    """Validate extension, declared media type, and inexpensive signatures."""

    suffix = PurePath(filename.replace("\\", "/")).suffix.lower()
    normalized_type = content_type.partition(";")[0].strip().lower()
    accepted_types = SUPPORTED_MEDIA_TYPES.get(suffix)
    if accepted_types is None or normalized_type not in accepted_types:
        raise UnsupportedMediaTypeError()
    if suffix == ".pdf" and not first_bytes.startswith(b"%PDF-"):
        raise UnsupportedMediaTypeError()
    is_utf16 = first_bytes.startswith((b"\xff\xfe", b"\xfe\xff"))
    if suffix != ".pdf" and b"\x00" in first_bytes and not is_utf16:
        raise InvalidUploadError()
    return normalized_type


def validate_user_metadata(
    metadata: dict[str, MetadataValue],
    max_bytes: int,
) -> dict[str, MetadataValue]:
    """Enforce bounded keys and serialized metadata size."""

    if len(metadata) > 64:
        raise InvalidUploadError(public_message="Document metadata contains too many fields.")
    for key in metadata:
        if not key or len(key) > 128 or key.startswith("_"):
            raise InvalidUploadError(public_message="Document metadata contains an invalid key.")
    encoded = json.dumps(metadata, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) > max_bytes:
        raise InvalidUploadError(public_message="Document metadata exceeds the configured limit.")
    return metadata
