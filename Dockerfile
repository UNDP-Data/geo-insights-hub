FROM python:3.11-slim

# 1. Install system utilities (git is required for sparse checkout and GitPython)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 2. Install uv and pixi (using bookworm-slim instead of the massive CUDA latest tag)
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /bin/
COPY --from=ghcr.io/prefix-dev/pixi:bookworm-slim /usr/local/bin/pixi /usr/local/bin/pixi

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# 3. Create virtualenv and install dependencies (cached layer)
RUN uv venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml uv.lock* ./
RUN uv pip install --no-cache -r pyproject.toml

# 4. Copy application source tree (contains src/insightshub and src/marimohub)
COPY src/ ./src/

# 5. Patch Marimo and link /workspace
RUN python3 /app/src/marimohub/patch.py && \
    ln -s /workspace /app/workspace

EXPOSE 80

# Expose both /app and /app/src for module imports (insightshub, marimohub)
ENV PYTHONPATH=/app/src:/app

# Default to production (false) unless --build-arg dev=true is passed
ARG dev=false
ENV DEV_MODE=${dev}

# Shell form of CMD: checks DEV_MODE at startup and uses 'exec' so uvicorn stays PID 1
CMD if [ "$DEV_MODE" = "true" ]; then \
      exec uvicorn insightshub.server:app --host 0.0.0.0 --port 80 --reload --reload-dir /app/src; \
    else \
      exec uvicorn insightshub.server:app --host 0.0.0.0 --port 80; \
    fi

