"""Run all Phase 0 regressions plus the complete Phase 1 gate."""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: Sequence[str]) -> None:
    print(f"\n> {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-docker",
        action="store_true",
        help="Skip both Phase 0 and Phase 1 Docker gates.",
    )
    parser.add_argument(
        "--skip-secret-scan",
        action="store_true",
        help="Skip the Phase 0 containerized secret scan.",
    )
    parser.add_argument(
        "--keep-stack",
        action="store_true",
        help="Leave the Phase 1 Compose stack running.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    phase0_command = ["uv", "run", "python", "scripts/validate_phase_0.py"]
    if args.skip_docker:
        phase0_command.append("--skip-docker")
    if args.skip_secret_scan:
        phase0_command.append("--skip-secret-scan")
    run(phase0_command)

    run(["uv", "sync", "--frozen", "--dev", "--extra", "ingestion"])
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
            "tests/security",
            "tests/integration",
            "--cov=app",
            "--cov-branch",
            "--cov-report=term-missing",
        ]
    )

    if args.skip_docker:
        print("\nPhase 1 code gates passed; Docker lifecycle smoke was skipped.")
        return

    run(["docker", "compose", "down", "--remove-orphans"])
    try:
        run(["docker", "compose", "up", "--detach", "--wait"])
        run(["uv", "run", "python", "scripts/smoke_phase_1.py"])
        run(["docker", "compose", "ps"])
    finally:
        if not args.keep_stack:
            run(["docker", "compose", "down", "--remove-orphans"])

    print("\nAll Phase 0 and Phase 1 regression gates passed.")


if __name__ == "__main__":
    main()
