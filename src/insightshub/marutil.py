from starlette.types import ASGIApp
import marimohub
import ast
import os
import importlib.util
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles
from fastapi import Request
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware



def get_global_metadata(target):
    """
    Returns only the global (module-level) docstring and the source code.
    """
    path = target

    # Resolve FQDN to file path if necessary
    if not os.path.exists(target):
        spec = importlib.util.find_spec(target)
        if spec and spec.origin:
            path = spec.origin
        else:
            return None, "Error: Target not found."

    try:
        with open(path, "r", encoding="utf-8") as f:
            source_code = f.read()

        tree = ast.parse(source_code)

        # ast.get_docstring specifically retrieves the
        # docstring of the node passed (the Module root)
        global_doc = ast.get_docstring(tree)

        return global_doc

    except Exception as e:
        return None, f"Error: {e}"