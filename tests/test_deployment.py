import compileall
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=["standalone", "repository"])
def deployment(tmp_path, request):
    project = tmp_path / "project"
    script_dir = project if request.param == "standalone" else project / "scripts/etc"
    script_dir.mkdir(parents=True)
    script = script_dir / "start.sh"
    shutil.copy2(ROOT / "scripts/etc/start.sh", script)
    shutil.copy2(ROOT / "docker-compose-deployment.yaml", project)
    (project / ".env").write_text("IMAGE_TAG=old\nIMAGE_PLATFORM=linux/arm64\nUNRELATED=preserved\n")
    binary = tmp_path / "bin"
    binary.mkdir()
    docker = binary / "docker"
    docker.write_text('''#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$CALLS"
if [[ $PWD != "$DEPLOY_DIR" ]]; then exit 9; fi
if [[ $* == *pull* && ${FAIL_PULL:-false} == true ]]; then exit 7; fi
if [[ $4 == port ]]; then printf '127.0.0.1:18000\\n'; fi
''')
    docker.chmod(0o755)
    env = {**os.environ, "PATH": f"{binary}:{os.environ['PATH']}",
           "CALLS": str(tmp_path / "calls"), "DEPLOY_DIR": str(project)}
    return project, script, env


def test_start_without_arguments_is_plain_compose(tmp_path, deployment):
    _, script, env = deployment
    completed = subprocess.run(["bash", str(script)], env=env, cwd=tmp_path,
                               check=True, capture_output=True, text=True)
    assert (tmp_path / "calls").read_text().splitlines() == [
        "compose -f docker-compose-deployment.yaml up -d",
        "compose -f docker-compose-deployment.yaml port be 8000",
    ]
    assert "http://127.0.0.1:18000/api/docs" in completed.stdout
    assert "http://127.0.0.1:18000/health/ready" in completed.stdout


def test_version_pull_then_persist_and_start(tmp_path, deployment):
    project, script, env = deployment
    completed = subprocess.run(["bash", str(script), "v1.2.3"], env=env, cwd=tmp_path,
                               check=True, capture_output=True, text=True)
    assert (tmp_path / "calls").read_text().splitlines() == [
        "compose -f docker-compose-deployment.yaml pull",
        "compose -f docker-compose-deployment.yaml up -d",
        "compose -f docker-compose-deployment.yaml port be 8000",
    ]
    assert "http://127.0.0.1:18000/api/docs" in completed.stdout
    value = (project / ".env").read_text()
    assert "IMAGE_TAG=v1.2.3\n" in value and "UNRELATED=preserved\n" in value
    assert value.count("IMAGE_TAG=") == 1


def test_failed_pull_keeps_selected_version(tmp_path, deployment):
    project, script, env = deployment
    before = (project / ".env").read_bytes()
    completed = subprocess.run(["bash", str(script), "v2"], cwd=tmp_path,
                               env={**env, "FAIL_PULL": "true"}, capture_output=True, text=True)
    assert completed.returncode == 7
    assert "접속 주소" not in completed.stdout
    assert (project / ".env").read_bytes() == before
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
    for name in ("build-start.sh", "build-push.sh"):
        assert "restart-policy=no" in (ROOT / "scripts" / name).read_text()
    assert "--push" not in (ROOT / "scripts/build-start.sh").read_text()
    assert "--load" not in (ROOT / "scripts/build-push.sh").read_text()


@pytest.mark.parametrize("compose_exit, version", [(0, "v0.2.0"), (7, "v0.2.0"), (0, None)])
def test_build_start_builds_through_compose_and_cleans_builder(tmp_path, compose_exit, version):
    project = tmp_path / "project"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(ROOT / "scripts/build-start.sh", scripts)
    shutil.copy2(ROOT / "docker-compose.yaml", project)
    binary = tmp_path / "bin"
    binary.mkdir()
    docker = binary / "docker"
    docker.write_text('''#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$CALLS"
if [[ $1 == compose && $4 == port ]]; then
    printf '127.0.0.1:18000\\n'
    exit 0
fi
if [[ $1 == compose ]]; then
    printf '%s\\n' "$PWD" "${BUILDX_BUILDER:-}" "${COMPOSE_BAKE:-}" "${LOCAL_IMAGE_TAG:-}" > "$BUILD_ENV"
    exit "$COMPOSE_EXIT"
fi
''')
    docker.chmod(0o755)
    env = {**os.environ, "PATH": f"{binary}:{os.environ['PATH']}",
           "CALLS": str(tmp_path / "calls"), "BUILD_ENV": str(tmp_path / "build-env"),
           "COMPOSE_EXIT": str(compose_exit), "LOCAL_IMAGE_TAG": "existing-local-version"}
    arguments = [version] if version else []
    completed = subprocess.run(["bash", str(scripts / "build-start.sh"), *arguments],
                               cwd=tmp_path, env=env, capture_output=True, text=True)
    assert completed.returncode == compose_exit
    directory, builder, bake, tag = (tmp_path / "build-env").read_text().splitlines()
    assert directory == str(project) and bake == "true"
    assert tag == (version or "existing-local-version")
    expected_calls = [
        f"buildx create --name {builder} --driver docker-container --driver-opt restart-policy=no",
        f"buildx inspect --builder {builder} --bootstrap",
        "compose -f docker-compose.yaml up -d --build",
    ]
    if compose_exit == 0:
        expected_calls.append("compose -f docker-compose.yaml port be 8000")
        assert "http://127.0.0.1:18000/api/docs" in completed.stdout
        assert "http://127.0.0.1:18000/health/ready" in completed.stdout
    else:
        assert "접속 주소" not in completed.stdout
    expected_calls.extend([
        f"buildx stop {builder}",
        f"buildx rm {builder}",
    ])
    assert (tmp_path / "calls").read_text().splitlines() == expected_calls


@pytest.mark.parametrize("build_exit, image_name", [
    (0, None), (0, "registry.example/team/backend"), (7, "registry.example/team/backend"),
])
def test_build_push_runs_alone_and_cleans_builder(tmp_path, build_exit, image_name):
    project = tmp_path / "project"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(ROOT / "scripts/build-push.sh", scripts)
    binary = tmp_path / "bin"
    binary.mkdir()
    docker = binary / "docker"
    docker.write_text('''#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$CALLS"
if [[ $1 == buildx && $2 == build ]]; then
    printf '%s\\n' "$PWD" > "$BUILD_DIR"
    exit "$BUILD_EXIT"
fi
''')
    docker.chmod(0o755)
    env = {**os.environ, "PATH": f"{binary}:{os.environ['PATH']}",
           "CALLS": str(tmp_path / "calls"), "BUILD_DIR": str(tmp_path / "build-dir"),
           "BUILD_EXIT": str(build_exit)}
    env.pop("IMAGE_NAME", None)
    if image_name is not None:
        env["IMAGE_NAME"] = image_name

    completed = subprocess.run(
        ["bash", str(scripts / "build-push.sh"), "v0.2.0"],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )

    assert completed.returncode == build_exit
    assert (tmp_path / "build-dir").read_text().strip() == str(project)
    calls = (tmp_path / "calls").read_text().splitlines()
    builder = calls[0].split()[3]
    image_name = image_name or "eagleindesert/fix-my-home-be"
    assert calls == [
        f"buildx create --name {builder} --driver docker-container --driver-opt restart-policy=no",
        f"buildx inspect --builder {builder} --bootstrap",
        f"buildx build --builder {builder} --platform linux/arm64 --tag {image_name}:v0.2.0 --push .",
        f"buildx stop {builder}",
        f"buildx rm {builder}",
    ]


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker CLI is not installed")
def test_local_compose_resolves_build_and_deployment_settings():
    # An explicit empty env file keeps this check independent of private .env files.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("FMH_", "LOCAL_", "IMAGE_", "COMPOSE_", "POSTGRES_", "DOCKER_SUBNET", "DOCKER_GATEWAY"))}
    env.update({
        "IMAGE_PLATFORM": "linux/arm64", "IMAGE_TAG": "deployed-version",
        "FMH_ENVIRONMENT": "production", "FMH_COOKIE_SECURE": "true",
        "FMH_PUBLIC_ORIGIN": "https://deployment.example",
        "FMH_DATABASE_URL": "postgresql+psycopg2://test:test@db:5432/test",
        "FMH_SESSION_SECRET": "testing-only-independent-secret-value",
        "POSTGRES_PASSWORD": "testing-only",
    })
    command = ["docker", "compose", "--env-file", "/dev/null", "-f", str(ROOT / "docker-compose.yaml"), "config", "--format", "json"]
    completed = subprocess.run(command, env=env, capture_output=True, text=True, check=True, timeout=30)
    config = json.loads(completed.stdout)
    assert set(config["services"]) == {"db", "migrate", "be", "worker"}
    for name, service in config["services"].items():
        assert service["platform"] == "linux/amd64"
        if name == "db":
            continue
        assert service["build"]["context"] == str(ROOT)
        assert service["image"] == "eagleindesert/fix-my-home-be:local"
        assert service["pull_policy"] == "build"
        assert service["environment"]["FMH_DATABASE_URL"] == env["FMH_DATABASE_URL"]
        assert service["environment"]["FMH_ENVIRONMENT"] == "development"
        assert service["environment"]["FMH_COOKIE_SECURE"] == "false"
        assert service["environment"]["FMH_PUBLIC_ORIGIN"] == "http://localhost:8000"
    assert config["services"]["be"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert config["services"]["worker"]["depends_on"]["db"]["condition"] == "service_healthy"


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
