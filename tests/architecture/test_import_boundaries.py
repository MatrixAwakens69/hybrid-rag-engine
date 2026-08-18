"""Enforce dependency direction without coupling tests to an extra tool."""

from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

FORBIDDEN_BY_LAYER = {
    "app/domain": {
        "fastapi",
        "starlette",
        "qdrant_client",
        "docling",
        "llama_index",
        "ragas",
        "structlog",
        "app.api",
        "app.application",
        "app.infrastructure",
    },
    "app/application": {
        "fastapi",
        "starlette",
        "qdrant_client",
        "docling",
        "llama_index",
        "ragas",
        "app.api",
        "app.infrastructure",
    },
    "app/api": {
        "qdrant_client",
        "docling",
        "llama_index",
        "ragas",
        "app.infrastructure",
    },
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def _matches(imported: str, forbidden: str) -> bool:
    return imported == forbidden or imported.startswith(f"{forbidden}.")


def test_layer_import_boundaries() -> None:
    violations: list[str] = []

    for relative_layer, forbidden_imports in FORBIDDEN_BY_LAYER.items():
        for path in (PROJECT_ROOT / relative_layer).rglob("*.py"):
            for imported in _imports(path):
                for forbidden in forbidden_imports:
                    if _matches(imported, forbidden):
                        violations.append(
                            f"{path.relative_to(PROJECT_ROOT)} imports forbidden {imported}"
                        )

    assert not violations, "\n".join(sorted(violations))
