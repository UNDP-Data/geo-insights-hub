import shutil
from insightshub import utils
import asyncio
from nicegui import ui
import textwrap
import logging
from pathlib import Path
from insightshub.config import settings
from insightshub.auth import User
import tempfile
import git
import os
import threading

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent.resolve()
NOTEBOOKS_DIR = (BASE_DIR / "notebooks").resolve()
os.environ['NOTEBOOKS_DIR'] = str(NOTEBOOKS_DIR)
_repo_lock = threading.Lock()


def repo_is_public(repo_name: str) -> bool:
    """
    Checks if a GitHub repo is public using GitPython without tokens.
    """
    public_url = f"https://github.com/{repo_name}.git"
    git_cmd = git.cmd.Git()
    try:
        git_cmd.ls_remote(public_url, env={"GIT_TERMINAL_PROMPT": "0"})
        return True
    except git.exc.GitCommandError:
        return False


def get_repo_url(user: User = None, repo_name=settings.nb_github_repo):
    """Returns the URL for cloning/pulling."""
    if repo_name.endswith('.git'):
        repo_name, _ = repo_name.split('.git')

    is_public = repo_is_public(repo_name=repo_name)
    if is_public:
        # Public repos return the clean URL for standard checkouts
        return f"https://github.com/{repo_name}.git"

    # Private repos MUST include the token to be checked out at all
    if user and user.is_authenticated and getattr(user, 'token', None):
        return f"https://x-access-token:{user.token}@github.com/{repo_name}.git"
        #return f"https://{user.name}:{user.token}@github.com/{repo_name}.git"

    return None


def get_push_url(user: User, repo_name=settings.nb_github_repo) -> str:
    """Always returns the authenticated URL specifically for pushing."""
    if not user or not user.is_authenticated or not getattr(user, 'token', None):
        raise PermissionError("Authenticated user with a valid token is required to push to GitHub.")

    if repo_name.endswith('.git'):
        repo_name, _ = repo_name.split('.git')

    return f"https://x-access-token:{user.token}@github.com/{repo_name}.git"


def sync_repo(user: User = None) -> bool:
    """Synchronizes the local notebooks directory with GitHub."""

    git_env = {"GIT_TERMINAL_PROMPT": "0"}
    repo_url = get_repo_url(user=user)
    if repo_url is None:
        # with caution, the user is not authenticated, repo is private, needs tor be DELETED
        # if NOTEBOOKS_DIR.exists():
        #     shutil.rmtree(NOTEBOOKS_DIR)
        return False

    with _repo_lock:
        if not NOTEBOOKS_DIR.exists():
            logger.info("Notebooks directory missing; performing initial clone...")
            repo = git.Repo.clone_from(repo_url, NOTEBOOKS_DIR, env=git_env)
            repo.remote("origin").set_url(repo_url)
        else:
            repo = git.Repo(NOTEBOOKS_DIR)
            origin = repo.remote("origin")
            try:
                origin.set_url(repo_url)
                repo.git.pull(repo_url, "main", env=git_env)
            finally:
                origin.set_url(repo_url)

    return True


def sync_repo_task(user: User = None) -> bool:
    try:
        return sync_repo(user=user)
    except git.exc.GitCommandError as e:
        err = str(e)
        if any(msg in err for msg in
               ["could not read Username", "Authentication failed", "exit code(128)", "exit code(1)"]):
            logger.error(e)
            logger.warning(
                f"Sync skipped: Repository '{settings.nb_github_repo}' is private or requires "
                "an authenticated user token."
            )
        else:
            logger.error(f"Git command failed during sync: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during sync_repo_task: {e}", exc_info=True)
        return False


async def fetch_notebook_source(notebook_path: str, user: User = None) -> str:
    """Uses Git sparse-checkout to pull a specific notebook file."""
    repo_url = get_repo_url(user=user)
    if not repo_url:
        raise PermissionError("Cannot access repository. Authentication required.")

    with tempfile.TemporaryDirectory() as tmpdir:
        repo = git.Repo.clone_from(
            repo_url,
            tmpdir,
            multi_options=["--no-checkout", "--depth", "1", "--filter=blob:none", "--sparse"]
        )

        repo.git.sparse_checkout("set", notebook_path)
        repo.git.checkout("main")
        target_file = Path(tmpdir) / notebook_path

        if not target_file.exists():
            raise FileNotFoundError(f"Notebook '{notebook_path}' not found in repository.")

        return target_file.read_text(encoding="utf-8")


async def new_notebok(notebook_path: str, user: User):
    if user is not None and not user.is_authenticated:
        logger.error(f'Invalid users should not be able to create a new notebook ....')
        return

    repo_url = get_repo_url(user=user)


    blank_content = textwrap.dedent('''\
        import marimo

        __generated_with = "0.9.0"
        app = marimo.App(width="medium")

        @app.cell
        def _():
            import marimo as mo
            return (mo,)

        @app.cell
        def _(mo):
            mo.md("# 🚀 New Notebook\\nStart building your insights here.")
            return

        if __name__ == "__main__":
            app.run()
    ''')

    loop = asyncio.get_event_loop()

    def _push_to_git():
        git_env = {"GIT_TERMINAL_PROMPT": "0"}
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = git.Repo.clone_from(repo_url, tmpdir, branch="main", depth=1, env=git_env)

            repo.config_writer().set_value("user", "name", str(user.name)).release()
            repo.config_writer().set_value("user", "email", str(user.email)).release()

            target_file = Path(tmpdir) / notebook_path
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text(blank_content, encoding="utf-8")

            repo.index.add([notebook_path])
            repo.index.commit(f"Initialize empty notebook: {notebook_path} by {user.name}")

            # --- PUSH INJECTION ---
            push_url = get_push_url(user=user)
            repo.remote(name='origin').set_url(push_url)

            push_info = repo.remote(name='origin').push()
            if push_info and (push_info[0].flags & push_info[0].ERROR):
                raise Exception(f"Git Push rejected: {push_info[0].summary}")

    await loop.run_in_executor(None, _push_to_git)


async def open_create_notebook_dialog(current_subpath: str, user: User):
    with ui.dialog().classes('backdrop-blur-sm') as dialog, ui.card().classes('w-full max-w-md p-6'):
        ui.label("New Notebook").classes('text-xl font-bold mb-4 text-gray-800')

        name_input = ui.input(
            label="Notebook Name",
            placeholder="e.g., q3_analysis"
        ).classes('w-full mb-6').props('autofocus')

        with ui.row().classes('w-full justify-end gap-2'):
            ui.button("Cancel", on_click=dialog.close).props('flat color=grey')

            async def handle_create():
                raw_name = name_input.value.strip()
                if not raw_name:
                    ui.notify("Please enter a notebook name", type='negative')
                    return

                filename = f"{raw_name.lower().replace(' ', '_')}.py"
                rel_path = str(Path(current_subpath) / filename) if current_subpath else filename

                dialog.close()
                ui.notify(f"Creating {filename} in GitHub...", type='info')

                try:
                    await new_notebok(rel_path, user)
                    ui.notify("Syncing server...", type='info')
                    await asyncio.to_thread(sync_repo_task, user)
                    ui.navigate.reload()
                except Exception as e:
                    logger.error(e)
                    ui.notify(f"Failed: {str(e)}", type='negative')

            ui.button("Create", on_click=handle_create).classes('undp-btn--small primary text-white')
    dialog.open()


async def delete_notebook_git(notebook_path: str, user: User):
    if user is not None and not user.is_authenticated:
        logger.error(f'Invalid users should not be able to delete a notebook')
        return

    repo_url = get_repo_url(user=user)
    loop = asyncio.get_event_loop()

    def _push_deletion():
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = git.Repo.clone_from(repo_url, tmpdir, branch="main", depth=1)

            repo.config_writer().set_value("user", "name", str(user.name)).release()
            repo.config_writer().set_value("user", "email", str(user.email)).release()

            target_file = Path(tmpdir) / notebook_path

            if target_file.exists():
                repo.git.rm(notebook_path)
                repo.index.commit(f"Delete notebook: {notebook_path} by {user.name}")

                # --- PUSH INJECTION ---
                push_url = get_push_url(user=user)
                repo.remote(name='origin').set_url(push_url)

                push_info = repo.remote(name='origin').push()
                if push_info and (push_info[0].flags & push_info[0].ERROR):
                    raise Exception(f"Git Push rejected: {push_info[0].summary}")
            else:
                raise FileNotFoundError("Notebook not found in repository.")

    await loop.run_in_executor(None, _push_deletion)


def confirm_delete_notebook(notebook_path: str, notebook_name: str, user: User):
    with ui.dialog().classes('backdrop-blur-sm') as dialog, ui.card().classes('p-6 max-w-sm'):
        ui.label("Delete Notebook?").classes('text-xl font-bold text-red-600 mb-2')
        ui.label(
            f"Are you sure you want to permanently delete '{notebook_name}'? This will remove it from the repository for everyone."
        ).classes('text-sm text-gray-700 mb-6')

        with ui.row().classes('w-full justify-end gap-2'):
            ui.button('Cancel', on_click=dialog.close).props('flat color=grey')

            async def perform_delete():
                dialog.close()
                ui.notify(f"Deleting {notebook_name}...", type='warning')
                try:
                    await delete_notebook_git(notebook_path, user)
                    await asyncio.to_thread(sync_repo_task, user)
                    ui.notify(f"Successfully deleted {notebook_name}", type='positive')
                    ui.navigate.reload()
                except Exception as e:
                    ui.notify(f"Error deleting: {str(e)}", type='negative')

            ui.button('Delete', color='negative', on_click=perform_delete).classes('text-white')
    dialog.open()


async def delete_folder_git(folder_path: str, user: User):
    if user is None or not user.is_authenticated:
        logger.error("Unauthenticated user attempted to delete a folder.")
        raise PermissionError("User is not authenticated.")

    repo_url = get_repo_url(user=user)
    loop = asyncio.get_event_loop()

    def _push_folder_deletion():
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = git.Repo.clone_from(repo_url, tmpdir, branch="main", depth=1)

            repo.config_writer().set_value("user", "name", str(user.name)).release()
            repo.config_writer().set_value("user", "email", str(user.email)).release()

            target_dir = Path(tmpdir) / folder_path

            if target_dir.exists() and target_dir.is_dir():
                repo.git.rm("-r", folder_path)
                repo.index.commit(f"Delete folder: {folder_path} by {user.name}")

                # --- PUSH INJECTION ---
                push_url = get_push_url(user=user)
                repo.remote(name="origin").set_url(push_url)

                push_info = repo.remote(name="origin").push()
                if push_info and (push_info[0].flags & push_info[0].ERROR):
                    raise Exception(f"Git Push rejected: {push_info[0].summary}")
            else:
                raise FileNotFoundError(f"Folder '{folder_path}' not found in repository.")

    await loop.run_in_executor(None, _push_folder_deletion)


def confirm_delete_folder(folder_path: str, folder_name: str, user: User):
    with ui.dialog().classes('backdrop-blur-sm') as dialog, ui.card().classes('p-6 max-w-sm'):
        ui.label("Delete Folder?").classes('text-xl font-bold text-red-600 mb-2')
        ui.label(
            f"Are you sure you want to permanently delete folder '{folder_name}' and ALL files/notebooks inside it? "
            "This will delete them from GitHub for everyone."
        ).classes('text-sm text-gray-700 mb-6')

        with ui.row().classes('w-full justify-end gap-2'):
            ui.button('Cancel', on_click=dialog.close).props('flat color=grey')

            async def perform_folder_delete():
                dialog.close()
                ui.notify(f"Deleting folder '{folder_name}'...", type='warning')
                try:
                    await delete_folder_git(folder_path, user)

                    local_target = (NOTEBOOKS_DIR / folder_path).resolve()
                    if local_target.exists() and local_target.is_dir():
                        shutil.rmtree(local_target, ignore_errors=True)

                    await asyncio.to_thread(sync_repo_task, user)
                    ui.notify(f"Successfully deleted {folder_name}", type='positive')
                    ui.navigate.reload()
                except Exception as e:
                    ui.notify(f"Error deleting folder: {str(e)}", type='negative')

            ui.button('Delete Folder', color='negative', on_click=perform_folder_delete).classes('text-white')
    dialog.open()