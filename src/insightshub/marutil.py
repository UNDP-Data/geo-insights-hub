import os
import ast
import importlib.util
import logging

logger = logging.getLogger(__name__)

def get_global_metadata(target):
    """
    Returns the global docstring if it exists, otherwise extracts the first
    standalone string or marimo markdown block (mo.md) from the notebook.
    """
    path = target

    if not os.path.exists(target):
        spec = importlib.util.find_spec(target)
        if spec and spec.origin:
            path = spec.origin
        else:
            return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            source_code = f.read()

        tree = ast.parse(source_code)

        # 1. Try standard Python docstring at the very top of the file
        global_doc = ast.get_docstring(tree)
        if global_doc:
            return global_doc

        # 2. Extract the first standalone string literal inside ANY cell function
        # This catches strings placed after imports (e.g., after `import marimo as mo`)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for stmt in node.body:
                    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                        if isinstance(stmt.value.value, str):
                            val = stmt.value.value.strip()
                            if val:
                                return val

        # 3. Fallback: Extract first mo.md() block
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'md':
                if node.args and hasattr(node.args[0], 'value'):
                    raw_markdown = node.args[0].value
                    if isinstance(raw_markdown, str):
                        # Get all non-empty lines
                        lines = [line.strip() for line in raw_markdown.split('\n') if line.strip()]

                        if not lines:
                            continue

                        # Try to find a line that IS NOT a header
                        description_lines = [line for line in lines if not line.startswith('#')]

                        if description_lines:
                            # If there is normal text, use the first two lines
                            return " ".join(description_lines[:2])
                        else:
                            # If there are ONLY headers (like your test), strip the '#' and return it!
                            first_header = lines[0].lstrip('#').strip()
                            return first_header

        return None

    except Exception as e:
        logger.error(f'Failed to extract metadata from notebook {target}. {e}')
        return None