"""Run MediaLab: ``python -m app`` (from the ``backend`` directory)."""

from __future__ import annotations

import argparse
import logging
import sys

import uvicorn

from .config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="MediaLab local API server")
    parser.add_argument("--reload", action="store_true", help="auto-reload on code changes (development)")
    args = parser.parse_args()

    settings = Settings.from_env()
    try:
        settings.validate_bind_host()
        # Check folders before uvicorn binds the port: a failed app startup under --reload
        # would otherwise leave the port open but unresponsive (the dev proxy then times out).
        settings.prepare_directories()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print(f"MediaLab API on http://{settings.host}:{settings.port}  (temporary files -> {settings.temp_dir})")
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
