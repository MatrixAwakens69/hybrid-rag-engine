"""Provision or rotate one tenant API key and print the raw token once."""

from __future__ import annotations

import argparse
import asyncio
import secrets

from qdrant_client import AsyncQdrantClient

from app.config import get_settings
from app.infrastructure.auth.qdrant_api_keys import QdrantAPIKeyAuthenticator

DEFAULT_SCOPES = (
    "documents:read",
    "documents:write",
    "documents:delete",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--key-id", required=True)
    parser.add_argument(
        "--scope",
        action="append",
        dest="scopes",
        help="Repeat for each scope; defaults to document read/write/delete.",
    )
    return parser.parse_args()


async def provision() -> None:
    args = parse_args()
    settings = get_settings()
    secret = secrets.token_urlsafe(32)
    client = AsyncQdrantClient(
        url=settings.qdrant_url,
        timeout=settings.qdrant_timeout_seconds,
    )
    try:
        authenticator = QdrantAPIKeyAuthenticator(
            client,
            settings.qdrant_auth_collection,
            bootstrap_key_id=settings.bootstrap_key_id,
        )
        await authenticator.initialize()
        await authenticator.seed_key(
            key_id=args.key_id,
            tenant_id=args.tenant_id,
            raw_secret=secret,
            scopes=frozenset(args.scopes or DEFAULT_SCOPES),
        )
    finally:
        await client.close()
    print("Store this token securely; it will not be shown again:")
    print(f"{args.key_id}.{secret}")


if __name__ == "__main__":
    asyncio.run(provision())
