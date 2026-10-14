#!/usr/bin/env python3
import asyncio
import json
import logging
import os
import sys

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from marimohub import mgit

logger = logging.getLogger("insights-hub.marimo-runner")
logging.basicConfig(level=logging.INFO)


# --- Starlette Endpoint Handlers ---

async def handle_session_info(request: Request) -> JSONResponse:
    """Returns runtime identity and branch metadata to hub_toolbar.js."""
    return JSONResponse({
        "username": os.environ.get("GIT_USER_NAME") or os.environ.get("GIT_AUTHOR_NAME") or "Unknown",
        "email": os.environ.get("GIT_USER_EMAIL") or os.environ.get("GIT_AUTHOR_EMAIL") or "",
        "session_id": os.environ.get("SESSION_ID", ""),
        "branch": os.environ.get("BRANCH_NAME", "main"),
        "notebook": os.environ.get("NOTEBOOK_REL_PATH") or os.environ.get("NB_REL_PATH") or "",
        "parent_hub_url": os.environ.get("PARENT_HUB_URL", "/"),
    })


async def handle_commit(request: Request) -> JSONResponse:
    """Stages notebook modifications and commits as the authenticated user."""
    try:
        body = {}
        raw = await request.body()
        if raw:
            body = json.loads(raw)

        message = body.get("message", "")
        # Offload blocking Git I/O to a worker thread
        result = await asyncio.to_thread(mgit.commit_and_push, message)
        return JSONResponse(result)
    except Exception as e:
        logger.exception("Commit failed")
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=400)


async def handle_publish(request: Request) -> JSONResponse:
    """Pushes branch, creates a GitHub Pull Request, and auto-merges or reports conflicts."""
    try:
        body = {}
        raw = await request.body()
        if raw:
            body = json.loads(raw)

        title = body.get("title")
        # Offload blocking Git & GitHub API calls to a worker thread
        result = await asyncio.to_thread(mgit.publish_to_pr, title)
        return JSONResponse(result)
    except Exception as e:
        logger.exception("Publish failed")
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=400)

async def handle_merge(request: Request) -> JSONResponse:
    """Merges the active branch's Pull Request via GitHub API."""
    try:
        # Offload blocking API call to a worker thread
        result = await asyncio.to_thread(mgit.merge_pr)
        return JSONResponse(result)
    except Exception as e:
        logger.exception("Merge failed")
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=400)

async def _delayed_kill():
    """Waits briefly for HTTP response to reach the browser before requesting pod teardown."""
    await asyncio.sleep(0.5)
    try:
        await asyncio.to_thread(mgit.terminate_session)
    except Exception as e:
        logger.error(f"Background session termination failed: {e}")


async def handle_kill(request: Request) -> JSONResponse:
    """Schedules cluster callback to delete the Kubernetes Job after responding to the client."""
    asyncio.create_task(_delayed_kill())
    return JSONResponse({"status": "terminating"})


def register_hub_routes(app):
    """
    Mounts /hub/* endpoints ahead of Marimo routes.
    Must be inserted at index 0 so Marimo's catch-all SPA static asset
    routes do not intercept them.
    """
    hub_routes = [
        Route("/hub/session-info", handle_session_info, methods=["GET"]),
        Route("/hub/commit", handle_commit, methods=["POST"]),
        Route("/hub/publish", handle_publish, methods=["POST"]),
        Route("/hub/merge", handle_merge, methods=["POST"]),
        Route("/hub/kill", handle_kill, methods=["POST"]),
    ]

    for route in reversed(hub_routes):
        app.routes.insert(0, route)

    logger.info("Successfully mounted Insights Hub routes: /hub/*")


# --- Monkey-Patching Marimo's Starlette Builder ---

def apply_marimo_patches():
    """Patches create_starlette_app across Marimo server modules."""
    patched = False

    target_modules = (
        "marimo._server.server",
        "marimo._server.main",
        "marimo._server.sessions",
    )

    for module_name in target_modules:
        try:
            mod = __import__(module_name, fromlist=["create_starlette_app"])
            if hasattr(mod, "create_starlette_app"):
                orig_create = getattr(mod, "create_starlette_app")

                def make_patched_create(orig_fn):
                    def _patched(*args, **kwargs):
                        app = orig_fn(*args, **kwargs)
                        register_hub_routes(app)
                        return app
                    return _patched

                setattr(mod, "create_starlette_app", make_patched_create(orig_create))
                patched = True
                logger.info(f"Patched create_starlette_app in {module_name}")
        except (ImportError, AttributeError) as err:
            logger.debug(f"Skipping patch on {module_name}: {err}")

    if not patched:
        logger.warning("Could not find create_starlette_app to patch in standard Marimo modules.")



# --- Execution Entrypoint ---

if __name__ == "__main__":
    apply_marimo_patches()

    # Pass execution directly to Marimo CLI
    from marimo._cli.cli import main
    main()