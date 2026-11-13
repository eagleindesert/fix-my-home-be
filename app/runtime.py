"""컨테이너의 빌드·실행 CPython 및 아키텍처 일치 확인."""

import importlib.util
import json
import platform
from pathlib import Path


def validate_runtime():
    path = Path(__file__).resolve().parents[1] / "build-info.json"
    if not path.exists():
        return
    manifest = json.loads(path.read_text())
    expected = {"amd64": "x86_64", "arm64": "aarch64"}[manifest["architecture"]]
    if platform.machine() != expected or manifest["magic"] != importlib.util.MAGIC_NUMBER.hex():
        raise RuntimeError("빌드 결과와 실행 CPU/CPython 바이트코드 형식이 일치하지 않습니다.")
    if manifest["python"].split()[0] != platform.python_version():
        raise RuntimeError("빌드와 실행 CPython 패치 버전이 일치하지 않습니다.")
