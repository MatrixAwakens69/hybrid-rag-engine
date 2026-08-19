"""Hash-only API-key authentication backed by a Qdrant control collection."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.domain.errors import UnauthorizedError
from app.domain.models import APIKeyRecord, TenantPrincipal
from app.domain.policies.ids import control_point_id


class QdrantAPIKeyAuthenticator:
    """Resolve key IDs and verify Argon2 hashes without persisting raw secrets."""

    def __init__(
        self,
        client: AsyncQdrantClient,
        collection_name: str,
        *,
        bootstrap_key_id: str,
    ) -> None:
        self._client = client
        self._collection_name = collection_name
        self._bootstrap_key_id = bootstrap_key_id
        self._hasher = PasswordHasher()

    async def initialize(self) -> None:
        if not await self._client.collection_exists(self._collection_name):
            await self._client.create_collection(
                collection_name=self._collection_name,
                vectors_config=VectorParams(size=1, distance=Distance.DOT),
                on_disk_payload=True,
            )

    async def seed_key(
        self,
        *,
        key_id: str,
        tenant_id: str,
        raw_secret: str,
        scopes: frozenset[str],
    ) -> None:
        """Idempotently create or rotate one operator-supplied key."""

        existing = await self._get_record(key_id)
        if existing is not None and await asyncio.to_thread(
            self._verify_without_error,
            existing.secret_hash,
            raw_secret,
        ):
            return
        secret_hash = await asyncio.to_thread(self._hasher.hash, raw_secret)
        record = APIKeyRecord(
            key_id=key_id,
            tenant_id=tenant_id,
            secret_hash=secret_hash,
            scopes=scopes,
            created_at=datetime.now(UTC),
        )
        await self._client.upsert(
            collection_name=self._collection_name,
            points=[
                PointStruct(
                    id=control_point_id("api-key", key_id),
                    vector=[0.0],
                    payload=record.model_dump(mode="json"),
                )
            ],
            wait=True,
        )

    async def authenticate(self, token: str) -> TenantPrincipal:
        key_id, secret = self._split_token(token)
        record = await self._get_record(key_id)
        if record is None or not record.enabled:
            raise UnauthorizedError()
        if record.expires_at is not None and record.expires_at <= datetime.now(UTC):
            raise UnauthorizedError(public_message="The API key has expired.")
        verified = await asyncio.to_thread(
            self._verify_without_error,
            record.secret_hash,
            secret,
        )
        if not verified:
            raise UnauthorizedError()
        return TenantPrincipal(
            tenant_id=record.tenant_id,
            key_id=record.key_id,
            scopes=record.scopes,
        )

    async def _get_record(self, key_id: str) -> APIKeyRecord | None:
        records = await self._client.retrieve(
            collection_name=self._collection_name,
            ids=[control_point_id("api-key", key_id)],
            with_payload=True,
            with_vectors=False,
        )
        if not records or records[0].payload is None:
            return None
        return APIKeyRecord.model_validate(records[0].payload)

    def _split_token(self, token: str) -> tuple[str, str]:
        if "." not in token:
            return self._bootstrap_key_id, token
        key_id, separator, secret = token.partition(".")
        if not separator or not key_id or not secret:
            raise UnauthorizedError()
        return key_id, secret

    def _verify_without_error(self, secret_hash: str, raw_secret: str) -> bool:
        try:
            return self._hasher.verify(secret_hash, raw_secret)
        except (VerifyMismatchError, VerificationError):
            return False
