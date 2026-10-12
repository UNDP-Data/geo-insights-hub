"""ASGI entry point: a FastAPI app with the NiceGUI frontend mounted on it."""

import logging
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from nicegui import app as nicegui_app
from nicegui import ui
from insightshub.config import settings
from insightshub import pages
import asyncio

logging.basicConfig(level=logging.INFO)
logging.getLogger("nicegui").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


STATIC_DIR = Path(__file__).parent / "static"


from insightshub.kube_session_manager import manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    # 1. Start cluster polling and discover active jobs
    await manager.startup()

    # # 2. Start background reaper for idle/stale sessions
    # reaper_task = asyncio.create_task(manager.cleanup_loop(max_idle_seconds=7200))

    yield  # Application (and NiceGUI) runs here

    # # --- SHUTDOWN (Fast exit for Docker) ---
    # reaper_task.cancel()
    # try:
    #     await reaper_task
    # except asyncio.CancelledError:
    #     pass

    # Stop the manager polling loop
    await manager.shutdown()

app = FastAPI(title=settings.app_name, lifespan=lifespan)


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}


nicegui_app.add_static_files("/static", STATIC_DIR)

ui.run_with(
    app,
    title=settings.app_name,
    storage_secret=settings.storage_secret,
    show_welcome_message=False,
)
