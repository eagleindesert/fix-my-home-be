import compileall
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def fake_deployment(tmp_path):
    shutil.copy2(ROOT / "start.sh", tmp_path)
    shutil.copy2(ROOT / "docker-compose-deployment.yaml", tmp_path)
    (tmp_path / ".env").write_text("IMAGE_TAG=old\nIMAGE_PLATFORM=linux/arm64\nUNRELATED=preserved\n")
    binary = tmp_path / "bin"
    binary.mkdir()
    docker = binary / "docker"
    docker.write_text('''#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$CALLS"
if [[ $* == *pull* && ${FAIL_PULL:-false} == true ]]; then exit 7; fi
''')
    docker.chmod(0o755)
    env = {**os.environ, "PATH": f"{binary}:{os.environ['PATH']}", "CALLS": str(tmp_path / "calls")}
    return env


def test_start_without_arguments_is_plain_compose(tmp_path):
    env = fake_deployment(tmp_path)
    subprocess.run(["bash", str(tmp_path / "start.sh")], env=env, cwd="/tmp", check=True)
    assert (tmp_path / "calls").read_text().splitlines() == ["compose -f docker-compose-deployment.yaml up -d"]


def test_version_pull_then_persist_and_start(tmp_path):
    env = fake_deployment(tmp_path)
    subprocess.run(["bash", str(tmp_path / "start.sh"), "v1.2.3"], env=env, check=True)
    assert (tmp_path / "calls").read_text().splitlines() == ["compose -f docker-compose-deployment.yaml pull", "compose -f docker-compose-deployment.yaml up -d"]
    value = (tmp_path / ".env").read_text()
    assert "IMAGE_TAG=v1.2.3\n" in value and "UNRELATED=preserved\n" in value
    assert value.count("IMAGE_TAG=") == 1


def test_failed_pull_keeps_selected_version(tmp_path):
    env = fake_deployment(tmp_path)
    before = (tmp_path / ".env").read_bytes()
    completed = subprocess.run(["bash", str(tmp_path / "start.sh"), "v2"], env={**env, "FAIL_PULL": "true"})
    assert completed.returncode == 7
    assert (tmp_path / ".env").read_bytes() == before
    assert "up -d" not in (tmp_path / "calls").read_text()


def test_three_file_compose_and_no_target_run():
    compose = yaml.safe_load((ROOT / "docker-compose-deployment.yaml").read_text())
    assert set(compose["services"]) == {"db", "migrate", "be", "worker"}
    for name, service in compose["services"].items():
        assert "build" not in service and "env_file" not in service
        assert all(not volume.startswith((".", "/")) for volume in service.get("volumes", []))
    assert compose["services"]["be"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert compose["services"]["be"]["ports"][0].startswith("127.0.0.1:")
    runtime = (ROOT / "Dockerfile").read_text().split(" AS runtime\n")[1]
    assert not any(line.startswith("RUN ") for line in runtime.splitlines())
    assert "/.venv/bin" not in runtime
    assert "restart-policy=no" in (ROOT / "scripts/build-common.sh").read_text()
    assert "--push" not in (ROOT / "scripts/build-start.sh").read_text()
    assert "--load" not in (ROOT / "scripts/build-push.sh").read_text()


def test_sourceless_api_and_alembic_imports(tmp_path):
    for folder in ("app", "migrations"):
        shutil.copytree(ROOT / folder, tmp_path / folder, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        assert compileall.compile_dir(tmp_path / folder, quiet=1, legacy=True)
        for path in (tmp_path / folder).rglob("*.py"):
            path.unlink()
    shutil.copy2(ROOT / "alembic.ini", tmp_path)
    env = {**os.environ, "FMH_DATABASE_URL": f"sqlite:///{tmp_path}/compiled.db", "FMH_LOG_DIR": str(tmp_path / "logs"), "PYTHONPATH": str(tmp_path)}
    invocation = ["uv", "run", "--no-project", "--no-sync", "--python", sys.executable, "python"]
    subprocess.run([*invocation, "-m", "app.migrate"], cwd=tmp_path, env=env, check=True, timeout=30)
    subprocess.run([*invocation, "-c", "from app.main import app; from app.worker import run_once; assert len(app.openapi()['paths']) == 70"],
                   cwd=tmp_path, env=env, check=True, timeout=30)
    assert not list((tmp_path / "app").rglob("*.py"))
