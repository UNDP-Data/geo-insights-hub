import logging
import os
import git
import httpx

logger = logging.getLogger("insights-hub.mgit")
logging.basicConfig(level=logging.INFO)

# --- Configuration & Environment Variables ---

REPO_DIR = os.environ.get("WORKSPACE_DIR", "/workspace")
NOTEBOOK_REL_PATH = os.environ.get("NOTEBOOK_REL_PATH") or os.environ.get("NB_REL_PATH", "")
SESSION_ID = os.environ.get("SESSION_ID", "")
BRANCH_NAME = os.environ.get("BRANCH_NAME", "main")
BASE_BRANCH = os.environ.get("BASE_BRANCH", "main")

# GitHub Repository full path (e.g. "org/repo-name")
raw_repo = os.environ.get("NB_GITHUB_REPO", "")
REPO_FULL_NAME = raw_repo.removesuffix(".git")

# Authentication Token
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("NB_GITHUB_TOKEN", "")

# Identity
GIT_USER_NAME = (
    os.environ.get("GIT_USER_NAME")
    or os.environ.get("GIT_AUTHOR_NAME")
    or "Insights Hub User"
)
GIT_USER_EMAIL = (
    os.environ.get("GIT_USER_EMAIL")
    or os.environ.get("GIT_AUTHOR_EMAIL")
    or "hub-user@undp.org"
)

# Hub Teardown Callback
HUB_CALLBACK_URL = os.environ.get("HUB_CALLBACK_URL") or os.environ.get("PARENT_HUB_URL")
HUB_CALLBACK_TOKEN = os.environ.get("HUB_CALLBACK_TOKEN", "")


# --- Git Helpers ---

def get_repo() -> git.Repo:
    """Initializes GitPython Repo and sets the authenticated remote origin."""
    if not os.path.exists(REPO_DIR):
        raise FileNotFoundError(f"Workspace directory '{REPO_DIR}' not found.")

    repo = git.Repo(REPO_DIR)

    if GITHUB_TOKEN and REPO_FULL_NAME:
        auth_url = f"https://oauth2:{GITHUB_TOKEN}@github.com/{REPO_FULL_NAME}.git"
        try:
            origin = repo.remote("origin")
            origin.set_url(auth_url)
        except ValueError:
            repo.create_remote("origin", auth_url)

    return repo


def push_branch(repo: git.Repo) -> None:
    """Pushes commits on the active branch to remote origin."""
    logger.info(f"Pushing branch '{BRANCH_NAME}' to remote origin...")
    repo.git.push("-u", "origin", BRANCH_NAME)


# --- Core Actions ---

def commit_and_push(message: str | None = None) -> dict:
    """Stages notebook changes, creates a signed commit, and pushes to GitHub."""
    repo = get_repo()

    # Ensure on dedicated session branch
    if repo.active_branch.name != BRANCH_NAME:
        try:
            repo.git.checkout(BRANCH_NAME)
        except git.GitCommandError:
            repo.git.checkout("-b", BRANCH_NAME)

    # Stage notebook file or all modified files
    if NOTEBOOK_REL_PATH and os.path.exists(os.path.join(REPO_DIR, NOTEBOOK_REL_PATH)):
        repo.git.add(NOTEBOOK_REL_PATH)
    else:
        repo.git.add(all=True)

    # If no diffs, push current state and return clean status
    if not repo.is_dirty(untracked_files=True) and not repo.index.diff("HEAD"):
        latest_commit = repo.head.commit
        push_branch(repo)
        return {
            "status": "clean",
            "commit_hex": latest_commit.hexsha[:7],
            "message": "No new modifications to commit. Pushed current branch state.",
        }

    author = git.Actor(GIT_USER_NAME, GIT_USER_EMAIL)
    commit_msg = message.strip() if message else f"Update {NOTEBOOK_REL_PATH or 'notebook'}"
    commit = repo.index.commit(commit_msg, author=author, committer=author)

    logger.info(f"Committed {commit.hexsha[:7]} by {GIT_USER_NAME} <{GIT_USER_EMAIL}>")
    push_branch(repo)

    return {
        "status": "success",
        "commit_hex": commit.hexsha[:7],
        "message": commit_msg,
    }


def publish_and_merge(title: str | None = None) -> dict:
    """Pushes latest commits, creates a PR on GitHub, and attempts auto-squash merge."""
    if not GITHUB_TOKEN or not REPO_FULL_NAME:
        raise ValueError("Missing GitHub credentials or repository configuration.")

    repo = get_repo()
    push_branch(repo)

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    pr_title = title or f"Notebook Update: {NOTEBOOK_REL_PATH} ({SESSION_ID})"
    pr_body = (
        f"Automated PR from Insights Hub notebook edit session.\n\n"
        f"- **Author:** {GIT_USER_NAME} ({GIT_USER_EMAIL})\n"
        f"- **Session ID:** `{SESSION_ID}`\n"
        f"- **Notebook:** `{NOTEBOOK_REL_PATH}`\n"
        f"- **Source Branch:** `{BRANCH_NAME}`"
    )

    with httpx.Client(timeout=20.0) as client:
        # Create PR
        create_pr_url = f"https://api.github.com/repos/{REPO_FULL_NAME}/pulls"
        create_payload = {
            "title": pr_title,
            "head": BRANCH_NAME,
            "base": BASE_BRANCH,
            "body": pr_body,
        }

        pr_resp = client.post(create_pr_url, headers=headers, json=create_payload)

        if pr_resp.status_code == 201:
            pr_data = pr_resp.json()
        elif pr_resp.status_code == 422:
            # PR already exists: find open PR for this branch
            logger.info("PR already exists. Retrieving existing PR...")
            list_resp = client.get(
                create_pr_url,
                headers=headers,
                params={"head": f"{REPO_FULL_NAME.split('/')[0]}:{BRANCH_NAME}", "state": "open"},
            )
            list_resp.raise_for_status()
            open_prs = list_resp.json()
            if not open_prs:
                raise RuntimeError("GitHub reported existing PR, but none were open.")
            pr_data = open_prs[0]
        else:
            pr_resp.raise_for_status()

        pr_number = pr_data["number"]
        pr_url = pr_data["html_url"]

        # Attempt Squash Merge
        merge_url = f"https://api.github.com/repos/{REPO_FULL_NAME}/pulls/{pr_number}/merge"
        merge_payload = {
            "commit_title": f"{pr_title} (#{pr_number})",
            "merge_method": "squash",
        }

        merge_resp = client.put(merge_url, headers=headers, json=merge_payload)

        if merge_resp.status_code == 200:
            logger.info(f"Auto-merged PR #{pr_number}")
            return {"status": "merged", "pr_number": pr_number, "pr_url": pr_url}
        elif merge_resp.status_code in (405, 409):
            logger.warning(f"Merge blocked/conflict on PR #{pr_number} (HTTP {merge_resp.status_code})")
            return {
                "status": "conflict",
                "pr_number": pr_number,
                "pr_url": pr_url,
                "detail": "PR created but cannot auto-merge due to branch rules or conflicts.",
            }
        else:
            merge_resp.raise_for_status()


def terminate_session() -> None:
    """Calls parent Hub API to delete the Job and HTTPRoute resources."""
    if not HUB_CALLBACK_URL:
        logger.warning("No HUB_CALLBACK_URL defined. Skipping session teardown.")
        return

    headers = {}
    if HUB_CALLBACK_TOKEN:
        headers["Authorization"] = f"Bearer {HUB_CALLBACK_TOKEN}"

    target_url = f"{HUB_CALLBACK_URL.rstrip('/')}/{SESSION_ID}"

    with httpx.Client(timeout=10.0) as client:
        try:
            resp = client.delete(target_url, headers=headers)
            if resp.status_code in (404, 405):
                resp = client.post(f"{target_url}/terminate", headers=headers)
            resp.raise_for_status()
            logger.info(f"Teardown triggered for session {SESSION_ID}")
        except Exception as err:
            logger.error(f"Teardown callback failed at {target_url}: {err}")
            raise