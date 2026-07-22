# syntax=docker/dockerfile:1
# One image: Node builds the React SPA, then FastAPI serves the API AND that
# built bundle (same origin). Build from the portal/ dir:  docker build -t archipellabs-portal .

# --- stage 1: build the React SPA -> /build/dist ---------------------------
FROM node:22-alpine AS frontend
WORKDIR /build
# The portal is self-contained — its small UI kit lives in src/ui, so the build
# needs no external design-system package. It's served at the root (no base path).
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- stage 2: FastAPI serving the API + the built SPA ----------------------
FROM python:3.14-slim AS runtime
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend/app ./app
# The SPA bundle lands in ./static, which app/main.py serves (see STATIC_DIR).
COPY --from=frontend /build/dist ./static
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
