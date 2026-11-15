#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if ! command -v uv >/dev/null 2>&1; then
  printf 'E2E 실행에 uv가 필요합니다. uv 설치 후 uv sync --locked를 실행하세요.\n' >&2
  exit 1
fi

export UV_CACHE_DIR="${UV_CACHE_DIR:-${TMPDIR:-/tmp}/fix-my-home-e2e-uv}"
exec uv run --no-sync --no-env-file python scripts/e2e/runner.py "$@"
