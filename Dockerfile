# syntax=docker/dockerfile:1.7
ARG PYTHON_IMAGE=python:3.13-slim-bookworm
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.17

FROM --platform=$BUILDPLATFORM ${UV_IMAGE} AS native-uv
FROM --platform=$TARGETPLATFORM ${UV_IMAGE} AS target-uv

# Every RUN executes on the native build CPU. Target wheels are only unpacked.
FROM --platform=$BUILDPLATFORM ${PYTHON_IMAGE} AS compiler
ARG TARGETARCH
COPY --from=native-uv /uv /usr/local/bin/uv
WORKDIR /build
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    case "$TARGETARCH" in \
      arm64) wheel_platform=aarch64-manylinux_2_28 ;; \
      amd64) wheel_platform=x86_64-manylinux_2_28 ;; \
      *) exit 2 ;; \
    esac && \
    uv sync --locked --no-dev --no-install-project --no-build \
      --python /usr/local/bin/python --python-platform "$wheel_platform"
RUN apt-get update && apt-get install -y --no-install-recommends fonts-nanum && \
    rm -rf /var/lib/apt/lists/*
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY scripts/etc/prepare_image.py ./prepare_image.py
RUN uv run --no-project --no-sync --python /usr/local/bin/python python prepare_image.py "$TARGETARCH"

# No target-architecture commands run during the image build.
FROM --platform=$TARGETPLATFORM ${PYTHON_IMAGE} AS runtime
COPY --from=target-uv /uv /usr/local/bin/uv
COPY --from=compiler /build/.venv/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=compiler /usr/share/fonts/truetype/nanum/NanumGothic.ttf /usr/share/fonts/truetype/nanum/NanumGothic.ttf
COPY --from=compiler --chown=10001:10001 /out/app /app
COPY --from=compiler --chown=10001:10001 /out/runtime /var/lib/fmh
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_PYTHON_DOWNLOADS=never \
    UV_CACHE_DIR=/tmp/uv-cache FMH_STORAGE_DIR=/var/lib/fmh/media FMH_LOG_DIR=/var/lib/fmh/logs
USER 10001:10001
EXPOSE 8000
CMD ["uv", "run", "--no-project", "--no-sync", "--python", "/usr/local/bin/python", "python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--no-access-log", "--workers", "1"]
