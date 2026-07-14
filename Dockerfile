# syntax=docker/dockerfile:1

FROM node:22-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS backend
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /usr/local/bin/
WORKDIR /app/backend

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY backend/passage ./passage
RUN uv sync --frozen --no-dev

COPY --from=frontend-build /app/frontend/dist /app/frontend-dist

ENV PATH="/app/backend/.venv/bin:$PATH"
ENV PASSAGE_STATIC_DIR=/app/frontend-dist

EXPOSE 8000
CMD ["sh", "-c", "uvicorn passage.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
