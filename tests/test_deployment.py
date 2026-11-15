import compileall
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def deployment(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    script = project / "start.sh"
    shutil.copy2(ROOT / "start.sh", script)
    shutil.copy2(ROOT / "docker-compose-deployment.yaml", project)
    (project / ".env").write_text("IMAGE_TAG=old\nIMAGE_PLATFORM=linux/arm64\nUNRELATED=preserved\n")
    binary = tmp_path / "bin"
    binary.mkdir()
    docker = binary / "docker"
    docker.write_text('''#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$CALLS"
if [[ $PWD != "$DEPLOY_DIR" ]]; then exit 9; fi
if [[ $4 == pull || $4 == up ]]; then
    printf '%s|%s|%s\\n' "$4" "${IMAGE_TAG:-}" "${IMAGE_PLATFORM:-}" >> "$SELECTORS"
fi
if [[ $* == *pull* && ${FAIL_PULL:-false} == true ]]; then exit 7; fi
if [[ $4 == pull && ${CHANGE_DURING_PULL:-false} == true ]]; then
    printf 'CONCURRENT=preserved\\n' >> .env
fi
if [[ $4 == port ]]; then printf '127.0.0.1:18000\\n'; fi
''')
    docker.chmod(0o755)
    env = {**os.environ, "PATH": f"{binary}:{os.environ['PATH']}",
           "CALLS": str(tmp_path / "calls"), "DEPLOY_DIR": str(project),
           "SELECTORS": str(tmp_path / "selectors")}
    env.pop("IMAGE_TAG", None)
    env.pop("IMAGE_PLATFORM", None)
    return project, script, env


def test_start_without_arguments_is_plain_compose(tmp_path, deployment):
    project, script, env = deployment
    assert {path.name for path in project.iterdir()} == {
        "docker-compose-deployment.yaml", ".env", "start.sh",
    }
    assert os.access(script, os.X_OK)
    original = (project / ".env").read_bytes()
    completed = subprocess.run([str(script)], env=env, cwd=tmp_path,
                               check=True, capture_output=True, text=True)
    assert (tmp_path / "calls").read_text().splitlines() == [
        "compose -f docker-compose-deployment.yaml up -d",
        "compose -f docker-compose-deployment.yaml port be 8000",
    ]
    assert "http://127.0.0.1:18000/api/docs" in completed.stdout
    assert "http://127.0.0.1:18000/health/ready" in completed.stdout
    assert (project / ".env").read_bytes() == original


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
    assert stat.S_IMODE((project / ".env").stat().st_mode) == 0o600
    assert (tmp_path / "selectors").read_text().splitlines() == [
        "pull|v1.2.3|", "up|v1.2.3|",
    ]


def test_failed_pull_keeps_selected_version(tmp_path, deployment):
    project, script, env = deployment
    before = (project / ".env").read_bytes()
    completed = subprocess.run(["bash", str(script), "v2"], cwd=tmp_path,
                               env={**env, "FAIL_PULL": "true"}, capture_output=True, text=True)
    assert completed.returncode == 7
    assert "접속 주소" not in completed.stdout
    assert (project / ".env").read_bytes() == before
    assert "up -d" not in (tmp_path / "calls").read_text()
    assert not list(project.glob(".env.update.*"))


@pytest.mark.parametrize("quote", ["'", '"'])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_version_update_preserves_multiline_values_and_comments(
    tmp_path, deployment, quote, newline,
):
    project, script, env = deployment
    multiline = (
        f"MULTILINE={quote}dummy \\\\ and escaped \\{quote} quote\n"
        f"IMAGE_TAG=literal-content\nIMAGE_PLATFORM=literal-content\n"
        f"last{quote} # keep inline\n"
    )
    original = (
        '\ufeffexport IMAGE_TAG="old" # version note\n'
        "IMAGE_PLATFORM=linux/amd64 # platform note\n"
        + multiline
        + "EMPTY=\nBARE\nPAYLOAD='$(touch should-not-exist)' # literal\n"
    ).replace("\n", newline).encode()
    target = project / ".env"
    target.write_bytes(original)

    completed = subprocess.run(
        [str(script), "v2", "--platform", "linux/arm64"], cwd=tmp_path, env=env,
        check=True, capture_output=True, text=True,
    )

    expected = original.replace(
        b'export IMAGE_TAG="old"', b"IMAGE_TAG=v2",
    ).replace(b"IMAGE_PLATFORM=linux/amd64 #", b"IMAGE_PLATFORM=linux/arm64 #")
    assert target.read_bytes() == expected
    assert not (project / "should-not-exist").exists()
    assert not list(project.glob(".env.update.*"))
    assert "dummy" not in completed.stdout + completed.stderr
    assert "literal-content" not in completed.stdout + completed.stderr


@pytest.mark.parametrize("original", [
    "SECRET='dummy-secret\n",
    'SECRET="dummy-secret" unexpected\n',
    "SECRET=dummy-secret\nSECRET=another-secret\n",
    "not a key dummy-secret\n",
])
def test_version_update_rejects_invalid_env_without_leaking_or_changing_it(
    tmp_path, deployment, original,
):
    project, script, env = deployment
    target = project / ".env"
    target.write_text(original)
    metadata = target.stat()

    completed = subprocess.run(
        [str(script), "v2"], cwd=tmp_path, env=env, capture_output=True, text=True,
    )

    assert completed.returncode == 2
    assert target.read_text() == original
    assert target.stat().st_mtime_ns == metadata.st_mtime_ns
    assert not (tmp_path / "calls").exists()
    assert not list(project.glob(".env.update.*"))
    assert "dummy-secret" not in completed.stdout + completed.stderr
    assert "another-secret" not in completed.stdout + completed.stderr


def test_version_update_does_not_overwrite_a_concurrent_edit(tmp_path, deployment):
    project, script, env = deployment
    original = (project / ".env").read_bytes()

    completed = subprocess.run(
        [str(script), "v2"], cwd=tmp_path,
        env={**env, "CHANGE_DURING_PULL": "true"}, capture_output=True, text=True,
    )

    assert completed.returncode == 2
    assert (project / ".env").read_bytes() == original + b"CONCURRENT=preserved\n"
    assert "up -d" not in (tmp_path / "calls").read_text()
    assert not list(project.glob(".env.update.*"))


@pytest.mark.parametrize("original", ["", "# Settings\n", "UNRELATED=preserved"])
def test_version_update_adds_missing_selectors(tmp_path, deployment, original):
    project, script, env = deployment
    target = project / ".env"
    target.write_text(original)
    subprocess.run(
        [str(script), "--platform", "linux/amd64", "v2"],
        cwd=tmp_path, env=env, check=True, capture_output=True, text=True,
    )
    assert target.read_text() == (
        (original.rstrip("\n") + "\n" if original else "")
        + "IMAGE_TAG=v2\nIMAGE_PLATFORM=linux/amd64\n"
    )


@pytest.mark.parametrize("platform", [None, "linux/arm64", "linux/amd64"])
@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker CLI is not installed")
def test_deployed_version_and_platform_work_with_direct_compose(tmp_path, deployment, platform):
    project, script, env = deployment
    # Only this temporary fake .env is read by the real Compose config command.
    (project / ".env").write_text(
        "IMAGE_TAG=old\nIMAGE_PLATFORM=linux/amd64\n"
        "FMH_DATABASE_URL=postgresql+psycopg2://test:test@db:5432/test\n"
        "FMH_SESSION_SECRET=testing-only-independent-secret-value\n"
        "FMH_PUBLIC_ORIGIN=https://deployment.example\nPOSTGRES_PASSWORD=testing-only\n"
    )
    arguments = ["v2"] + (["--platform", platform] if platform else [])
    subprocess.run([str(script), *arguments], cwd=tmp_path, env=env, check=True, capture_output=True)
    direct_env = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("FMH_", "IMAGE_", "COMPOSE_", "POSTGRES_"))
    }
    completed = subprocess.run(
        [shutil.which("docker"), "compose", "-f", "docker-compose-deployment.yaml",
         "config", "--format", "json"],
        cwd=project, env=direct_env, check=True, capture_output=True, text=True,
    )
    config = json.loads(completed.stdout)
    for name, service in config["services"].items():
        assert service["platform"] == (platform or "linux/amd64")
        if name != "db":
            assert service["image"] == "eagleindesert/fix-my-home-be:v2"
    expected_override = platform or ""
    assert (tmp_path / "selectors").read_text().splitlines() == [
        f"pull|v2|{expected_override}", f"up|v2|{expected_override}",
    ]


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


@pytest.mark.parametrize("relative_script", [
    "start.sh", "scripts/build-start.sh", "scripts/build-push.sh",
])
@pytest.mark.parametrize("arguments", [
    ["v2", "--platform"],
    ["v2", "--platform", ""],
    ["v2", "--platform", "linux/386"],
    ["v2", "--platform", "linux/arm64", "--platform", "linux/amd64"],
    ["invalid/tag"],
])
def test_invalid_options_stop_before_docker_or_env_access(tmp_path, relative_script, arguments):
    project = tmp_path / "project"
    script = project / relative_script
    script.parent.mkdir(parents=True)
    shutil.copy2(ROOT / relative_script, script)
    binary = tmp_path / "bin"
    binary.mkdir()
    docker = binary / "docker"
    docker.write_text('#!/usr/bin/env bash\nprintf "unexpected Docker call\\n" > "$CALLS"\n')
    docker.chmod(0o755)
    env = {
        **os.environ, "PATH": f"{binary}:{os.environ['PATH']}",
        "CALLS": str(tmp_path / "calls"),
    }

    completed = subprocess.run(
        [str(script), *arguments], cwd=tmp_path, env=env, capture_output=True, text=True,
    )

    assert completed.returncode == 2
    assert not (tmp_path / "calls").exists()
    assert not (project / ".runtime").exists()
    assert not (project / ".env").exists()


@pytest.mark.parametrize("compose_exit, version", [(0, "v0.2.0"), (7, "v0.2.0"), (0, None)])
@pytest.mark.parametrize("platform", [None, "linux/arm64"])
def test_build_start_builds_through_compose_and_cleans_builder(tmp_path, compose_exit, version, platform):
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
    printf '%s\\n' "$PWD" "${BUILDX_BUILDER:-}" "${COMPOSE_BAKE:-}" "${LOCAL_IMAGE_TAG:-}" "${LOCAL_IMAGE_PLATFORM:-}" > "$BUILD_ENV"
    exit "$COMPOSE_EXIT"
fi
''')
    docker.chmod(0o755)
    env = {**os.environ, "PATH": f"{binary}:{os.environ['PATH']}",
           "CALLS": str(tmp_path / "calls"), "BUILD_ENV": str(tmp_path / "build-env"),
           "COMPOSE_EXIT": str(compose_exit), "LOCAL_IMAGE_TAG": "existing-local-version",
           "LOCAL_IMAGE_PLATFORM": "linux/amd64"}
    arguments = ([version] if version else []) + (["--platform", platform] if platform else [])
    completed = subprocess.run(["bash", str(scripts / "build-start.sh"), *arguments],
                               cwd=tmp_path, env=env, capture_output=True, text=True)
    assert completed.returncode == compose_exit
    directory, builder, bake, tag, selected_platform = (tmp_path / "build-env").read_text().splitlines()
    assert directory == str(project) and bake == "true"
    assert tag == (version or "existing-local-version")
    assert selected_platform == (platform or "linux/amd64")
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


@pytest.mark.parametrize("build_exit, image_name, platform", [
    (0, None, None),
    (0, "registry.example/team/backend", "linux/amd64"),
    (7, "registry.example/team/backend", "linux/amd64"),
])
def test_build_push_runs_alone_and_cleans_builder(tmp_path, build_exit, image_name, platform):
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

    invocation = ["bash", str(scripts / "build-push.sh")]
    options = ["--platform", platform] if platform else []
    completed = subprocess.run(
        [*invocation, "v0.2.0", *options],
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
        f"buildx build --builder {builder} --platform {platform or 'linux/arm64'} --tag {image_name}:v0.2.0 --push .",
        f"buildx stop {builder}",
        f"buildx rm {builder}",
    ]
    history_directory = project / ".runtime/build-push"
    histories = list(history_directory.glob("*.tag"))
    assert not list(history_directory.glob(".push.*"))
    if build_exit:
        assert not histories
        assert "현재 푸시 버전" not in completed.stdout
        return

    assert "이전 푸시 버전 (이 컴퓨터): 기록 없음" in completed.stdout
    assert "현재 푸시 버전: v0.2.0" in completed.stdout
    assert len(histories) == 1 and histories[0].read_text() == "v0.2.0\n"
    failed = subprocess.run(
        [*invocation, "v0.3.0", *options], cwd=tmp_path,
        env={**env, "BUILD_EXIT": "7"}, capture_output=True, text=True,
    )
    assert failed.returncode == 7
    assert "현재 푸시 버전" not in failed.stdout
    assert histories[0].read_text() == "v0.2.0\n"
    following = subprocess.run(
        [*invocation, "v0.4.0", *options], cwd=tmp_path, env=env,
        check=True, capture_output=True, text=True,
    )
    assert "이전 푸시 버전 (이 컴퓨터): v0.2.0" in following.stdout
    assert "현재 푸시 버전: v0.4.0" in following.stdout
    assert histories[0].read_text() == "v0.4.0\n"
    other_platform = "linux/arm64" if platform == "linux/amd64" else "linux/amd64"
    separate = subprocess.run(
        [*invocation, "v0.5.0", "--platform", other_platform],
        cwd=tmp_path, env=env, check=True, capture_output=True, text=True,
    )
    assert "이전 푸시 버전 (이 컴퓨터): 기록 없음" in separate.stdout
    assert histories[0].read_text() == "v0.4.0\n"
    assert not list(history_directory.glob(".push.*"))


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
        assert service["environment"]["FMH_PUBLIC_ORIGIN"] == "http://localhost:8002"
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
