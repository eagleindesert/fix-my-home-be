"""네이티브 CPython에서 바이트코드 생성 및 대상 wheel ELF 아키텍처 확인."""

import compileall
import importlib.util
import json
import shutil
import struct
import sys
from pathlib import Path


def prepare(root, output, architecture):
    expected_machine = {"amd64": 62, "arm64": 183}[architecture]
    if sys.version_info[:2] != (3, 13):
        raise RuntimeError("배포 바이트코드는 CPython 3.13에서 생성해야 합니다.")
    native_files = list((root / ".venv/lib/python3.13/site-packages").rglob("*.so*"))
    for path in native_files:
        header = path.read_bytes()[:20]
        if header.startswith(b"\x7fELF"):
            machine = struct.unpack("<H" if header[5] == 1 else ">H", header[18:20])[0]
            if machine != expected_machine:
                raise RuntimeError(f"대상 CPU와 다른 wheel입니다: {path.name}")
    for name in ("app", "migrations"):
        source = root / name
        if not compileall.compile_dir(source, quiet=1, legacy=True, force=True,
                                      stripdir=str(root), prependdir="/app", optimize=0):
            raise RuntimeError("바이트코드 컴파일 실패")
        for path in source.rglob("*.pyc"):
            if "__pycache__" in path.parts:
                continue
            destination = output / "app" / path.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
    shutil.copy2(root / "alembic.ini", output / "app/alembic.ini")
    for directory in ("media", "logs"):
        (output / "runtime" / directory).mkdir(parents=True, exist_ok=True)
    manifest = {"python": sys.version, "magic": importlib.util.MAGIC_NUMBER.hex(),
                "architecture": architecture, "nativeExtensions": len(native_files)}
    (output / "app/build-info.json").write_text(json.dumps(manifest, indent=2)+"\n")


if __name__ == "__main__":
    prepare(Path("/build"), Path("/out"), sys.argv[1])
