FROM python:3.11-slim

# 1. Install system utilities (git is required for sparse checkout and GitPython)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 2. Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN uv venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 3. Copy dependency definitions and install (cached layer)
# Ensure pyproject.toml includes: gitpython, httpx, marimo, nicegui, fastapi, uvicorn
COPY pyproject.toml uv.lock* ./
RUN uv pip install --no-cache -r pyproject.toml

# 4. Copy application source tree (contains src/insightshub and src/marimohub)
COPY src/ ./src/

# 5. Patch Marimo
RUN python3 /app/src/marimohub/patch.py

EXPOSE 80

# Expose both /app and /app/src for module imports (insightshub, marimohub)
ENV PYTHONPATH=/app/src:/app



# Default command runs the main Insights Hub UI.
# Spawned Marimo Kubernetes Jobs will override this command with:
# ['python3', '-m', 'marimohub.mrun', 'edit', ...]
CMD ["uvicorn", "insightshub.server:app", "--host", "0.0.0.0", "--port", "80", "--reload", "--reload-dir", "/app/src"]