"""Phase 0 worker process with graceful shutdown and no ingestion behavior."""

from __future__ import annotations

import asyncio
import signal
from contextlib import suppress

import structlog

from app.api.logging import configure_logging
from app.config import get_settings

logger = structlog.get_logger(__name__)


async def run() -> None:
    """Stay alive for Compose while Phase 1 adds manifest processing."""

    settings = get_settings()
    configure_logging(settings.log_level)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    for signal_name in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(signal_name, stop.set)

    logger.info("worker_started", revision=settings.app_revision)
    try:
        await stop.wait()
    finally:
        logger.info("worker_stopped")


def main() -> None:
    """Run the worker process."""

    asyncio.run(run())


if __name__ == "__main__":
    main()
