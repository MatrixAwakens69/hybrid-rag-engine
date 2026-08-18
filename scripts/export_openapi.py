"""Export the deterministic Phase 0 OpenAPI contract snapshot."""

from __future__ import annotations

import json
from pathlib import Path

from app.config import Environment, Settings
from app.main import create_app

SNAPSHOT_PATH = Path("tests/contract/snapshots/openapi.json")


def main() -> None:
    settings = Settings(_env_file=None, environment=Environment.TEST, app_revision="contract")
    schema = create_app(settings).openapi()
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {SNAPSHOT_PATH}")


if __name__ == "__main__":
    main()
