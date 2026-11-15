"""실행기 단위 테스트: Docker와 HTTP 실행을 대체하여 제어 흐름만 확인한다.

이 테스트의 성공은 Docker E2E 성공을 의미하지 않는다. 실제 E2E 검증은
docker-compose.yaml을 실행한 뒤 scripts/e2e/run.sh로 별도로 수행한다.
"""

import json
import stat
from types import SimpleNamespace

import pytest

from scripts.e2e import runner


class FakeDocker:
    """Docker 메타데이터와 fixture 실행 결과만 제공하는 실행기용 대역."""

    def __init__(self):
        self.calls = []
        self.fail_actions = set()
        self.missing_service = None
        self.environment = {
            "environment": "development", "databaseFingerprint": "test-fingerprint",
            "publicOrigin": "http://localhost:8000", "rootPath": "",
            "aiExpectedStatus": "FAILED", "aiConfigFingerprint": "test-ai-fingerprint",
            "storageDir": "/var/lib/fmh/media", "databaseServerAddress": "172.30.0.2",
        }
        self.worker_environment = dict(self.environment)
        self.metadata = {}
        for service in ("db", "migrate", "be", "worker"):
            self.metadata[service] = {
                "status": "exited" if service == "migrate" else "running",
                "health": "healthy" if service in ("db", "be") else None,
                "exitCode": 0,
                "image": "sha256:database" if service == "db" else "sha256:application",
                "configFiles": str(runner.ROOT / "docker-compose.yaml"),
                "command": ["python", "-m", "app.worker"] if service == "worker" else [],
                "mounts": [{
                    "Type": "volume", "Destination": "/var/lib/fmh/media",
                    "Name": "test-media-data", "RW": True,
                }] if service in ("be", "worker") else [],
            }

    def call(self, arguments, *, input_text=None):
        self.calls.append(list(arguments))
        command = arguments[0]
        if command == "info":
            return "29.9.3"
        if command == "ps":
            label = next(value for value in arguments if value.startswith(
                "label=com.docker.compose.service=",
            ))
            service = label.rsplit("=", 1)[1]
            return "" if service == self.missing_service else service + "-container"
        if command == "inspect":
            if "NetworkSettings" in arguments[2]:
                return "172.30.0.2"
            return json.dumps(self.metadata[arguments[-1].removesuffix("-container")])
        if command == "port":
            assert arguments[1:] == ["be-container", "8000/tcp"]
            return "127.0.0.1:18000"
        if command == "exec":
            assert input_text and "def prepare(" in input_text
            assert "--no-project" in arguments and "--no-env-file" in arguments
            action, run_id = arguments[-2:]
            if action in self.fail_actions:
                raise runner.CheckError("fixture " + action + " failed")
            if action == "check":
                return json.dumps(self.worker_environment if arguments[2] == "worker-container"
                                  else self.environment)
            if action == "prepare":
                return json.dumps({"runId": run_id, "password": "private-test-password"})
            if action == "cleanup":
                return json.dumps({"status": "cleaned", "runId": run_id})
        raise AssertionError(f"예상하지 않은 Docker 호출: {arguments!r}")

    @property
    def actions(self):
        return [call[-2] for call in self.calls if call[0] == "exec"]


@pytest.fixture
def execution(monkeypatch, tmp_path):
    docker = FakeDocker()
    state = SimpleNamespace(
        docker=docker, output=tmp_path / "results", http_calls=[], http_exit=0,
        interrupt=False, config_path=None, http_failure=None,
    )
    monkeypatch.setattr(runner, "Docker", lambda: docker)
    monkeypatch.setattr(runner.sys.stdin, "isatty", lambda: False)

    def run_http(args, config_path, result_dir, base_url, emit):
        state.config_path = config_path
        assert stat.S_IMODE(config_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(result_dir.stat().st_mode) == 0o700
        assert json.loads(config_path.read_text())["password"] == "private-test-password"
        state.http_calls.append({"suite": args.suite, "base_url": base_url})
        if state.interrupt:
            raise KeyboardInterrupt
        if state.http_failure:
            (result_dir / "summary.json").write_text(json.dumps({
                "passed": False, "failure": state.http_failure,
            }))
        emit("HTTP 실행 대역: 실제 네트워크 검증 아님")
        return state.http_exit

    monkeypatch.setattr(runner, "run_http", run_http)
    state.run = lambda *args: runner.main(["--output", str(state.output), *args])
    return state


@pytest.mark.parametrize("arguments", [["--suite", "unknown"], ["--suite"],
                                       ["--http-timeout", "0"], ["--poll-timeout", "nan"]])
def test_invalid_arguments_fail_before_docker_access_or_output_creation(execution, arguments):
    with pytest.raises(SystemExit) as stopped:
        execution.run(*arguments)
    assert stopped.value.code == 2
    assert execution.docker.calls == []
    assert not execution.output.exists()


def test_help_does_not_require_docker(execution, capsys):
    with pytest.raises(SystemExit) as stopped:
        execution.run("--help")
    assert stopped.value.code == 0
    assert "--suite" in capsys.readouterr().out
    assert execution.docker.calls == []


@pytest.mark.parametrize("arguments,suite", [([], "api"), (["--suite", "api"], "api"),
                                             (["--suite", "scenarios"], "scenarios")])
def test_runner_passes_selected_suite_and_cleans_private_material(execution, capsys, arguments, suite):
    assert execution.run(*arguments) == 0
    assert execution.http_calls == [{"suite": suite, "base_url": "http://localhost:18000"}]
    assert execution.docker.actions == ["check", "check", "prepare", "cleanup"]
    assert execution.config_path is not None and not execution.config_path.exists()
    report = json.loads((execution.output / "run-result.json").read_text())
    assert report["status"] == "PASSED" and report["cleanup"] == "PASSED"
    assert report["exitCode"] == 0 and report["suite"] == suite
    captured = capsys.readouterr()
    assert "private-test-password" not in captured.out + captured.err
    for path in execution.output.iterdir():
        assert "private-test-password" not in path.read_text()
    assert all(call[0] in {"info", "ps", "inspect", "port", "exec"}
               for call in execution.docker.calls)


def test_explicit_project_and_url_are_forwarded(execution):
    assert execution.run("--project", "separate-e2e", "--base-url", "http://127.0.0.1:19000/") == 0
    assert execution.http_calls[0]["base_url"] == "http://127.0.0.1:19000"
    selectors = [call for call in execution.docker.calls if call[0] == "ps"]
    assert all("label=com.docker.compose.project=separate-e2e" in call for call in selectors)
    assert not any(call[0] == "port" for call in execution.docker.calls)


@pytest.mark.parametrize("answer,suite", [("", "api"), ("2", "scenarios")])
def test_terminal_menu_selects_suite(execution, monkeypatch, answer, suite):
    monkeypatch.setattr(runner.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: answer)
    assert execution.run() == 0
    assert execution.http_calls[0]["suite"] == suite


@pytest.mark.parametrize("service,field,value", [
    ("be", "configFiles", "/project/docker-compose-deployment.yaml"),
    ("worker", "status", "exited"), ("db", "health", "unhealthy"),
    ("migrate", "exitCode", 1), ("migrate", "status", "running"),
    ("worker", "command", ["python", "-m", "unrelated"]),
    ("worker", "image", "sha256:different-application"), ("worker", "mounts", []),
])
def test_incorrect_stack_stops_before_preparing_data(execution, service, field, value):
    execution.docker.metadata[service][field] = value
    assert execution.run() == 1
    assert execution.docker.actions == []
    assert execution.http_calls == []
    report = json.loads((execution.output / "run-result.json").read_text())
    assert report["status"] == "FAILED" and report["cleanup"] == "NOT_STARTED"


def test_missing_worker_stops_before_preparing_data(execution):
    execution.docker.missing_service = "worker"
    assert execution.run() == 1
    assert execution.docker.actions == []
    assert execution.http_calls == []


def test_different_api_and_worker_database_stops_before_preparing_data(execution):
    execution.docker.worker_environment["databaseFingerprint"] = "different-database"
    assert execution.run() == 1
    assert execution.docker.actions == ["check", "check"]
    assert execution.http_calls == []


@pytest.mark.parametrize("field,value", [
    ("databaseServerAddress", "192.0.2.3"), ("storageDir", "/tmp/separate-storage"),
])
def test_matching_app_settings_must_still_use_compose_database_and_storage(execution, field, value):
    execution.docker.environment[field] = value
    execution.docker.worker_environment[field] = value
    assert execution.run() == 1
    assert execution.docker.actions == ["check", "check"]
    assert execution.http_calls == []


@pytest.mark.parametrize("database_address,expected_exit", [
    ("172.30.0.2/32", 0),
    ("172.30.0.2/24", 0),
    ("172.30.0.3/24", 1),
    ("192.0.2.3/32", 1),
    (None, 1),
    ("", 1),
    ("invalid-address", 1),
])
def test_database_identity_compares_host_address_without_netmask(
    execution, database_address, expected_exit,
):
    # PostgreSQL의 inet→text 결과는 /32를 포함한다. Docker는 bare IP를 반환한다.
    # 같은 서브넷의 다른 호스트를 허용하지 않고, 호스트 자체의 동일성을 비교한다.
    execution.docker.environment["databaseServerAddress"] = database_address
    execution.docker.worker_environment["databaseServerAddress"] = database_address

    assert execution.run() == expected_exit

    if expected_exit == 0:
        assert len(execution.http_calls) == 1
        assert execution.docker.actions == ["check", "check", "prepare", "cleanup"]
    else:
        assert execution.http_calls == []
        assert execution.docker.actions == ["check", "check"]


def test_partial_prepare_failure_still_attempts_cleanup(execution):
    execution.docker.fail_actions.add("prepare")
    assert execution.run() == 1
    assert execution.docker.actions == ["check", "check", "prepare", "cleanup"]
    assert execution.http_calls == []
    report = json.loads((execution.output / "run-result.json").read_text())
    assert report["status"] == "FAILED" and report["cleanup"] == "PASSED"


@pytest.mark.parametrize("http_exit,cleanup_failure,expected", [
    (17, False, 17), (0, True, 1), (17, True, 17), (-15, False, 143),
])
def test_failure_exit_codes_and_cleanup_are_preserved(execution, http_exit, cleanup_failure, expected):
    execution.http_exit = http_exit
    if cleanup_failure:
        execution.docker.fail_actions.add("cleanup")
    assert execution.run() == expected
    assert execution.docker.actions[-1] == "cleanup"
    assert not execution.config_path.exists()
    report = json.loads((execution.output / "run-result.json").read_text())
    assert report["status"] == "FAILED" and report["exitCode"] == expected
    assert report["cleanup"] == ("FAILED" if cleanup_failure else "PASSED")


def test_interrupt_cleans_fixture_and_credentials(execution):
    execution.interrupt = True
    assert execution.run() == 130
    assert execution.docker.actions[-1] == "cleanup"
    assert not execution.config_path.exists()
    report = json.loads((execution.output / "run-result.json").read_text())
    assert report["error"] == "INTERRUPTED" and report["exitCode"] == 130


def test_http_failure_reason_is_repeated_after_cleanup(execution, capsys):
    execution.http_exit = 1
    execution.http_failure = "Worker job expected SUCCEEDED; got FAILED; errorCode=AI_INVALID_OUTPUT"
    assert execution.run() == 1
    report = json.loads((execution.output / "run-result.json").read_text())
    assert report["error"] == execution.http_failure
    assert report["cleanup"] == "PASSED"
    console = capsys.readouterr().out
    assert "[실패 원인] " + execution.http_failure in console
    assert console.index("[PASS] 테스트 자료 정리 완료") < console.index("[실패 원인]")


def test_keep_data_retains_fixture_but_removes_credentials(execution):
    assert execution.run("--keep-data") == 0
    assert execution.docker.actions == ["check", "check", "prepare"]
    assert not execution.config_path.exists()
    report = json.loads((execution.output / "run-result.json").read_text())
    assert report["cleanup"] == "KEPT"


def test_existing_results_are_not_overwritten(execution):
    execution.output.mkdir()
    previous = execution.output / "summary.json"
    previous.write_text("previous run")
    assert execution.run() == 1
    assert previous.read_text() == "previous run"
    assert execution.docker.calls == []


def test_output_file_is_rejected_without_overwrite(execution):
    execution.output.write_text("existing file")
    assert execution.run() == 1
    assert execution.output.read_text() == "existing file"
    assert execution.docker.calls == []


def test_docker_errors_do_not_expose_raw_stderr(monkeypatch):
    monkeypatch.setattr(runner.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=1, stdout="", stderr="postgresql://admin:private-test-password@db/fmh",
    ))
    with pytest.raises(runner.CheckError) as failed:
        runner.Docker().call(["exec", "be-container", "command"])
    assert "private-test-password" not in str(failed.value)
    assert "exit 1" in str(failed.value)
