# Note: This Dockerfile is designed to be built with the repository root as the context.
# Example: docker build -f backend/Dockerfile .

FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy dependency files
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Final stage
FROM python:3.11-slim-bookworm

WORKDIR /app/backend

# Copy the virtual environment from builder
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy backend application code
COPY backend/app ./app

# Copy required global assets/configuration from the repo root
COPY portals.yml ../portals.yml
COPY templates ../templates

# Expose the port FastAPI will run on
EXPOSE 8000

# Start uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
