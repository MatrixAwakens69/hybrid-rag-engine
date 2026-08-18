"""Run the complete, repeatable Phase 0 regression gate."""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GITLEAKS_IMAGE = "zricethezav/gitleaks:v8.28.0"


def run(command: Sequence[str]) -> None:
    """Run one visible gate command from the repository root."""

    print(f"\n> {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def validate_image_user(image: str) -> None:
    """Require runtime images to declare the non-root application user."""

    print(f"\n> validate non-root user for {image}", flush=True)
    completed = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Config.User}}", image],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    configured_user = completed.stdout.strip()
    if configured_user not in {"appuser", "10001"}:
        raise RuntimeError(f"{image} has unsafe runtime user: {configured_user!r}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-docker",
        action="store_true",
        help="Skip image build, Compose startup, and HTTP smoke tests.",
    )
    parser.add_argument(
        "--skip-secret-scan",
        action="store_true",
        help="Skip the containerized gitleaks scan.",
    )
    parser.add_argument(
        "--keep-stack",
        action="store_true",
        help="Leave the validated Compose stack running.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run(["uv", "lock", "--check"])
    run(["uv", "sync", "--frozen", "--dev"])
    run(["uv", "run", "ruff", "check", "."])
    run(["uv", "run", "ruff", "format", "--check", "."])
    run(["uv", "run", "mypy", "app", "worker"])
    run(
        [
            "uv",
            "run",
            "pytest",
            "tests/unit",
            "tests/contract",
            "tests/architecture",
            "--cov=app",
            "--cov-branch",
            "--cov-report=term-missing",
        ]
    )

    if not args.skip_secret_scan:
        run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{ROOT}:/repo",
                GITLEAKS_IMAGE,
                "detect",
                "--source=/repo",
                "--config=/repo/.gitleaks.toml",
                "--no-git",
                "--redact",
                "--no-banner",
            ]
        )

    if args.skip_docker:
        print("\nPhase 0 code gates passed; Docker gates were skipped.")
        return

    run(["docker", "compose", "config", "--quiet"])
    try:
        run(["docker", "compose", "build"])
        validate_image_user("hybrid-rag-engine-api")
        validate_image_user("hybrid-rag-engine-worker")
        run(["docker", "compose", "up", "--detach", "--wait"])
        run(["uv", "run", "python", "scripts/smoke_test.py"])
        run(["docker", "compose", "ps"])
    finally:
        if not args.keep_stack:
            run(["docker", "compose", "down"])

    print("\nAll Phase 0 regression gates passed.")


if __name__ == "__main__":
    main()
