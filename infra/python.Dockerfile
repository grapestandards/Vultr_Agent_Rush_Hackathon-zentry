# Shared image for the Python services; PACKAGE selects which workspace member to install.
FROM ghcr.io/astral-sh/uv:0.8.15-python3.12-bookworm-slim
ARG PACKAGE
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock .python-version ./
COPY libs ./libs
COPY data/generator/pyproject.toml ./data/generator/pyproject.toml
COPY services/api/pyproject.toml ./services/api/pyproject.toml
COPY services/worker/pyproject.toml ./services/worker/pyproject.toml
COPY services/trainer/pyproject.toml ./services/trainer/pyproject.toml
COPY data/generator/src ./data/generator/src
COPY services/api/src ./services/api/src
COPY services/worker/src ./services/worker/src
COPY services/trainer/src ./services/trainer/src
RUN uv sync --frozen --no-dev --package ${PACKAGE}
ENV PATH="/app/.venv/bin:$PATH"
