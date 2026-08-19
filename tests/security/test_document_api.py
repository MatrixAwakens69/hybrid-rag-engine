"""Authenticated document API and tenant-isolation regression tests."""

from __future__ import annotations

import httpx
import pytest


def _auth(token: str = "tenant-a-key") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_all_document_routes_require_authentication(
    phase1_client: httpx.AsyncClient,
) -> None:
    upload = await phase1_client.post(
        "/v1/documents",
        files={"file": ("notes.txt", b"evidence", "text/plain")},
    )
    listing = await phase1_client.get("/v1/documents")
    get = await phase1_client.get("/v1/documents/unknown")
    delete = await phase1_client.delete("/v1/documents/unknown")

    assert {upload.status_code, listing.status_code, get.status_code, delete.status_code} == {401}
    assert upload.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_upload_is_idempotent_and_cross_tenant_ids_are_hidden(
    phase1_client: httpx.AsyncClient,
) -> None:
    request = {
        "files": {"file": ("../../secret?.txt", b"grounded evidence", "text/plain")},
        "data": {"metadata_json": '{"department":"legal"}'},
        "headers": _auth(),
    }
    first = await phase1_client.post("/v1/documents", **request)
    repeated = await phase1_client.post("/v1/documents", **request)

    assert first.status_code == 202
    assert repeated.status_code == 202
    document_id = first.json()["document_id"]
    assert repeated.json()["document_id"] == document_id

    own = await phase1_client.get(f"/v1/documents/{document_id}", headers=_auth())
    other = await phase1_client.get(
        f"/v1/documents/{document_id}",
        headers=_auth("tenant-b-key"),
    )
    listing = await phase1_client.get("/v1/documents", headers=_auth())

    assert own.status_code == 200
    assert own.json()["document"]["filename"] == "secret_.txt"
    assert listing.json()["items"][0]["document_id"] == document_id
    assert other.status_code == 404
    assert other.json()["error"]["code"] == "document_not_found"


@pytest.mark.asyncio
async def test_cross_tenant_delete_is_hidden_and_owner_delete_is_idempotent(
    phase1_client: httpx.AsyncClient,
) -> None:
    uploaded = await phase1_client.post(
        "/v1/documents",
        files={"file": ("notes.txt", b"delete me", "text/plain")},
        headers=_auth(),
    )
    document_id = uploaded.json()["document_id"]

    hidden = await phase1_client.delete(
        f"/v1/documents/{document_id}",
        headers=_auth("tenant-b-key"),
    )
    first = await phase1_client.delete(f"/v1/documents/{document_id}", headers=_auth())
    repeated = await phase1_client.delete(f"/v1/documents/{document_id}", headers=_auth())

    assert hidden.status_code == 404
    assert first.status_code == 202
    assert first.json()["status"] == "deleting"
    assert repeated.json()["status"] == "deleting"


@pytest.mark.asyncio
async def test_mime_spoofing_and_reserved_metadata_are_rejected(
    phase1_client: httpx.AsyncClient,
) -> None:
    spoofed = await phase1_client.post(
        "/v1/documents",
        files={"file": ("report.pdf", b"plain text", "application/pdf")},
        headers=_auth(),
    )
    forged = await phase1_client.post(
        "/v1/documents",
        files={"file": ("notes.txt", b"text", "text/plain")},
        data={"metadata_json": '{"_tenant_id":"tenant-b"}'},
        headers=_auth(),
    )

    assert spoofed.status_code == 415
    assert forged.status_code == 422
