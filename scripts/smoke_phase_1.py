"""Authenticated Docker smoke test for the complete Phase 1 document lifecycle."""

from __future__ import annotations

import json
import os
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

BASE_URL = os.environ.get("PHASE1_BASE_URL", "http://127.0.0.1:8000")
API_KEY = os.environ.get("PHASE1_API_KEY", "change-me")


def _request(
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    request_headers = {"Authorization": f"Bearer {API_KEY}", **(headers or {})}
    request = Request(
        f"{BASE_URL}{path}",
        data=body,
        headers=request_headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read())
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} returned {exc.code}: {detail}") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"{method} {path} returned a non-object body")
    return payload


def _upload() -> dict[str, Any]:
    boundary = f"phase1-{uuid4().hex}"
    content = b"# Phase 1\n\nThis document proves authenticated ingestion and deletion.\n"
    body = (
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="metadata_json"\r\n\r\n'
            '{"purpose":"phase1-smoke"}\r\n'
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="phase1-smoke.md"\r\n'
            "Content-Type: text/markdown\r\n\r\n"
        ).encode()
        + content
        + f"\r\n--{boundary}--\r\n".encode()
    )
    return _request(
        "POST",
        "/v1/documents",
        body=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )


def _wait_for_status(document_id: str, expected: set[str], timeout: float = 90) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = _request("GET", f"/v1/documents/{document_id}")
        status = payload["document"]["status"]
        if status in expected:
            return payload
        time.sleep(0.5)
    raise TimeoutError(f"document {document_id} did not reach {sorted(expected)}")


def main() -> None:
    accepted = _upload()
    document_id = str(accepted["document_id"])
    ready = _wait_for_status(document_id, {"ready", "failed"})
    if ready["document"]["status"] != "ready":
        raise RuntimeError(f"document processing failed: {ready}")

    repeated = _upload()
    if repeated["document_id"] != document_id:
        raise RuntimeError("idempotent re-upload produced a different document ID")

    listing = _request("GET", "/v1/documents")
    if document_id not in {item["document_id"] for item in listing["items"]}:
        raise RuntimeError("ready document is absent from tenant-scoped listing")

    deleting = _request("DELETE", f"/v1/documents/{document_id}")
    if deleting["status"] not in {"deleting", "deleted"}:
        raise RuntimeError(f"unexpected deletion status: {deleting}")
    deleted = _wait_for_status(document_id, {"deleted", "failed"})
    if deleted["document"]["status"] != "deleted":
        raise RuntimeError(f"document deletion failed: {deleted}")

    print(f"Phase 1 lifecycle smoke test passed for {document_id}.")


if __name__ == "__main__":
    main()
