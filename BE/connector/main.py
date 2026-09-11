"""Entrypoint for the Plantwise Local Connector. Runs the local config web
UI and the background job poller together in one process, one event loop.
This is the file PyInstaller packages into the single executable (see
packaging/connector.spec).
"""
from __future__ import annotations

import asyncio
import logging
import sys
import webbrowser
from pathlib import Path

# Allow running this file directly (`python main.py`) without installing the
# package — matches how PyInstaller will invoke it too.
sys.path.insert(0, str(Path(__file__).parent))

import uvicorn

from app.config import CONFIG_DIR, LOG_FILE
from app.poller import poll_loop
from app.web import app as web_app

LOCAL_PORT = 8765


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
    )


async def run() -> None:
    setup_logging()
    logger = logging.getLogger("connector.main")
    logger.info("starting Plantwise Local Connector — config dir: %s", CONFIG_DIR)

    stop_event = asyncio.Event()
    poller_task = asyncio.create_task(poll_loop(stop_event))

    server = uvicorn.Server(uvicorn.Config(web_app, host="127.0.0.1", port=LOCAL_PORT, log_level="warning"))

    try:
        webbrowser.open(f"http://127.0.0.1:{LOCAL_PORT}")
    except Exception:
        logger.debug("could not auto-open a browser — open http://127.0.0.1:%d manually", LOCAL_PORT)

    try:
        await server.serve()
    finally:
        stop_event.set()
        await poller_task


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
