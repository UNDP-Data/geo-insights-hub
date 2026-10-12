import os
import shutil
import marimo

def patch_marimo():
    static_dir = os.path.join(os.path.dirname(marimo.__file__), "_static")
    assets_dir = os.path.join(static_dir, "assets")

    # 1. Put mtoolbar.js into the assets directory
    os.makedirs(assets_dir, exist_ok=True)
    src_script = os.path.join(os.path.dirname(__file__), "mtoolbar.js")
    dst_script = os.path.join(assets_dir, "mtoolbar.js")

    if not os.path.exists(src_script):
        raise FileNotFoundError(f"Toolbar script not found at {src_script}")

    shutil.copy(src_script, dst_script)

    # 2. Update index.html to load from /assets/mtoolbar.js
    index_path = os.path.join(static_dir, "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Clean up old relative reference if present
    html = html.replace('<script src="./mtoolbar.js"></script>', '')

    script_tag = '<script src="/assets/mtoolbar.js"></script>'
    if script_tag not in html:
        html = html.replace("</body>", f"{script_tag}</body>")

    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html)

    print("Successfully patched Marimo with /assets/mtoolbar.js")

if __name__ == "__main__":
    patch_marimo()