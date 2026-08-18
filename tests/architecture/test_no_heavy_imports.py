"""Importing the API must not initialize future parser or model stacks."""

from __future__ import annotations

import json
import subprocess
import sys


def test_app_import_does_not_load_heavy_model_modules() -> None:
    modules = ["docling", "llama_index", "ragas", "sentence_transformers", "torch"]
    code = (
        "import json, sys; import app.main; "
        f"print(json.dumps({{name: name in sys.modules for name in {modules!r}}}))"
    )

    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    loaded = json.loads(completed.stdout.strip())

    assert loaded == dict.fromkeys(modules, False)
