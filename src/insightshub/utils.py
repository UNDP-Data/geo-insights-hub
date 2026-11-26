from pathlib import Path
import logging
from insightshub.gitui import NOTEBOOKS_DIR
from marimo._ast.load import load_app

logger = logging.getLogger(__name__)

def get_md_pages(notebooks_dir:Path=NOTEBOOKS_DIR) -> dict[str, Path]:
    pages: list[tuple[int, str, Path]] = []
    for path in Path(notebooks_dir).glob("*.md"):
        prefix, sep, slug = path.stem.partition(".")
        if sep and prefix.isdigit() and slug:
            pages.append((int(prefix), slug, path))
    pages.sort(key=lambda item: item[0])
    return {slug: path for _, slug, path in pages}

def is_marimo_notebook(python_file_path:str=None)->bool:
    try:
        app = load_app(python_file_path)
        app = None
        return True
    except Exception as e:
        return False