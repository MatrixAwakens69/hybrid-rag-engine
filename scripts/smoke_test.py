"""Smoke-test a running Phase 0 Docker stack."""

from __future__ import annotations

import json
from urllib.request import urlopen


def _get(path: str) -> dict[str, object]:
    with urlopen(f"http://127.0.0.1:8000{path}", timeout=5) as response:
        if response.status != 200:
            raise RuntimeError(f"{path} returned HTTP {response.status}")
        body = json.loads(response.read())
        if not isinstance(body, dict):
            raise TypeError(f"{path} returned a non-object body")
        return body


def main() -> None:
    live = _get("/health/live")
    ready = _get("/health/ready")
    if live.get("status") != "ok":
        raise RuntimeError(f"liveness failed: {live}")
    if ready.get("status") != "ok":
        raise RuntimeError(f"readiness failed: {ready}")
    dependencies = ready.get("dependencies")
    if not isinstance(dependencies, dict) or "qdrant" not in dependencies:
        raise RuntimeError(f"Qdrant readiness missing: {ready}")
    print("Phase 0 Docker smoke test passed.")


if __name__ == "__main__":
    main()
