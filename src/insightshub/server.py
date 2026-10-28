"""ASGI entry point: a FastAPI app with the NiceGUI frontend mounted on it."""

import logging
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI #, Request, BackgroundTasks
from nicegui import app as nicegui_app
from nicegui import ui
from insightshub.config import settings
from insightshub import pages
from insightshub.auth import CustomHeaderMiddleware
from kubernetes import client

logging.basicConfig(level=logging.INFO)
logging.getLogger("nicegui").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("uvicorn.access").setLevel(logging.ERROR)
# 2. Silence the "connection open" / "connection closed" logs
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)

# 3. (Optional) Silence Engine.IO/Socket.IO internal chatter
logging.getLogger("engineio.server").setLevel(logging.WARNING)
logging.getLogger("socketio.server").setLevel(logging.WARNING)

from insightshub.kube_session_manager import manager

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"





@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    # 1. Start cluster polling and discover active jobs
    await manager.startup()
    yield  # Application (and NiceGUI) runs here
    # Stop the manager polling loop
    await manager.shutdown()

app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(CustomHeaderMiddleware)


# @app.post("/git/sync")
# async def github_push_webhook(request: Request, background_tasks: BackgroundTasks):
#     # Run the git pull and cache rebuild in the background
#     # so GitHub gets an immediate 200 OK response
#     background_tasks.add_task(sync_repo_task)
#     return {"message": "Sync triggered"}




@app.delete("/api/sessions/{session_id}")
async def terminate_session(session_id: str):
    """Deletes the Marimo Job, triggering cascading cleanup of Service and Route."""
    batch_v1 = client.BatchV1Api()
    try:
        batch_v1.delete_namespaced_job(
            name=f"marimo-edit-{session_id}",
            namespace="marimo",
            propagation_policy="Foreground",
        )
        return {"status": "deleted"}
    except client.exceptions.ApiException as e:
        if e.status == 404:
            return {"status": "already_deleted"}
        raise

nicegui_app.add_static_files("/static", STATIC_DIR)

ui.run_with(
    app,
    title=settings.app_name,
    storage_secret=settings.storage_secret,
    show_welcome_message=False,
)
