from insightshub.config import settings
from insightshub.auth import User
from pathlib import Path
import os
import git
import logging
import threading


logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent.resolve()
NOTEBOOKS_DIR = (BASE_DIR / "notebooks").resolve()
os.environ['NOTEBOOKS_DIR'] = str(NOTEBOOKS_DIR)
_repo_lock = threading.Lock()

def sync_repo(user:User=None):

    if user is  None or not user.is_authenticated:
        return

    repo_url = f'https://oauth2:{user.token}@github.com/{settings.nb_github_repo}'
    with _repo_lock:
        if not NOTEBOOKS_DIR.exists():
            git.Repo.clone_from(repo_url, NOTEBOOKS_DIR)
        else:
            repo = git.Repo(NOTEBOOKS_DIR)
            repo.remotes.origin.pull()
            repo.remotes.origin.fetch()

def sync_repo_task(user:User=None):
    try:
        sync_repo(user=user)  # Your existing function that pulls Git and builds APP_CACHE
    except Exception as e:
        logger.error(f"Git sync failed: {e}")
