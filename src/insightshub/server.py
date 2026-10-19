"""ASGI entry point: a FastAPI app with the NiceGUI frontend mounted on it."""

import logging
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, BackgroundTasks
from nicegui import app as nicegui_app
from nicegui import ui
from insightshub.config import settings
import git
from insightshub import pages
from kubernetes import client
import asyncio

logging.basicConfig(level=logging.INFO)
logging.getLogger("nicegui").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


from insightshub.kube_session_manager import manager

def sync_repo():
    repo_url = f'https://oauth2:{settings.nb_github_token}@github.com/{settings.nb_github_repo}'
    if not pages.NOTEBOOKS_DIR.exists():
        git.Repo.clone_from(repo_url, pages.NOTEBOOKS_DIR)
    else:
        repo = git.Repo(pages.NOTEBOOKS_DIR)
        repo.remotes.origin.pull()
        repo.remotes.origin.fetch()


def sync_repo_task():
    try:
        sync_repo()  # Your existing function that pulls Git and builds APP_CACHE
    except Exception as e:
        logger.error(f"Git sync failed: {e}")

# 1. Create a native async background loop
async def periodic_sync():
    while True:
        # Run the synchronous git pull in a separate thread so it doesn't block the server
        await asyncio.to_thread(sync_repo_task)
        await asyncio.sleep(60)

@asynccontextmanager
async def lifespan(app: FastAPI):
    poll_task = asyncio.create_task(periodic_sync())
    # --- STARTUP ---
    # 1. Start cluster polling and discover active jobs
    await manager.startup()
    yield  # Application (and NiceGUI) runs here
    poll_task.cancel()
    # Stop the manager polling loop
    await manager.shutdown()

app = FastAPI(title=settings.app_name, lifespan=lifespan)




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
