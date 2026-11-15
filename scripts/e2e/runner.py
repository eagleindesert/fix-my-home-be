"""이미 실행 중인 로컬 Compose 서비스를 검증하고 실제 HTTP E2E를 실행한다."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from ipaddress import ip_address, ip_interface
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from urllib.parse import urlsplit
import uuid


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
INSPECT_FORMAT = (
    '{"status":{{json .State.Status}},'
    '"health":{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}},'
    '"exitCode":{{.State.ExitCode}},"image":{{json .Image}},'
    '"configFiles":{{json (index .Config.Labels "com.docker.compose.project.config_files")}},'
    '"command":{{json .Config.Cmd}},"mounts":{{json .Mounts}}}'
)


class CheckError(Exception):
    """비밀값을 포함하지 않는 실행 오류."""


class Docker:
    def call(self, arguments: list[str], *, input_text: str | None = None) -> str:
        try:
            result = subprocess.run(
                ["docker", *arguments], input=input_text, text=True,
                capture_output=True, timeout=120,
            )
        except FileNotFoundError as exc:
            raise CheckError("Docker CLI를 찾을 수 없습니다.") from exc
        except subprocess.TimeoutExpired as exc:
            raise CheckError(f"Docker {arguments[0]} 명령이 제한 시간을 초과했습니다.") from exc
        if result.returncode:
            # Docker/SQL 오류에 환경값이 섞일 수 있어 원문을 출력하지 않는다.
            if arguments[0] == "info":
                raise CheckError("Docker daemon에 접근할 수 없습니다. 실행 상태와 소켓 권한을 확인하세요.")
            if arguments[0] == "exec":
                messages = [line for line in result.stderr.splitlines()
                            if line.startswith(("E2E fixture:", "E2E fixture 실패 ("))]
                if messages:
                    raise CheckError(messages[-1])
            raise CheckError(f"Docker {arguments[0]} 실패 (exit {result.returncode}).")
        return result.stdout.strip()


def preflight(docker: Docker, project: str, emit) -> dict[str, str]:
    docker.call(["info", "--format", "{{.ServerVersion}}"])
    containers = {}
    states = {}
    for service in ("db", "migrate", "be", "worker"):
        ids = docker.call([
            "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}",
            "--filter", f"label=com.docker.compose.service={service}",
        ]).split()
        if len(ids) != 1:
            raise CheckError(f"{project}/{service}: 컨테이너가 정확히 1개여야 합니다 (현재 {len(ids)}개).")
        state = json.loads(docker.call(["inspect", "--format", INSPECT_FORMAT, ids[0]]))
        config_files = str(state.get("configFiles") or "").split(",")
        if not any(Path(path.strip()).name == "docker-compose.yaml" for path in config_files):
            raise CheckError(f"{service}: docker-compose.yaml로 생성된 로컬 컨테이너가 아닙니다.")
        if service == "migrate":
            if state["status"] != "exited" or state["exitCode"] != 0:
                raise CheckError("migrate: 마이그레이션이 정상 완료되지 않았습니다.")
        elif state["status"] != "running":
            raise CheckError(f"{service}: 실행 중이 아닙니다.")
        if service in ("db", "be") and state["health"] != "healthy":
            raise CheckError(f"{service}: healthcheck가 healthy가 아닙니다. 준비 완료 후 다시 실행하세요.")
        if service == "worker" and "app.worker" not in (state.get("command") or []):
            raise CheckError("worker: app.worker 프로세스 설정을 확인할 수 없습니다.")
        containers[service] = ids[0]
        states[service] = state
        emit(f"[PASS] Compose {service}: {state['status']} / {state['health'] or 'healthcheck 없음'}")
    if len({states[name]["image"] for name in ("be", "worker", "migrate")}) != 1:
        raise CheckError("be·worker·migrate의 이미지가 다릅니다. 같은 빌드로 실행하세요.")

    def media_volume(service):
        return [mount.get("Name") for mount in states[service]["mounts"]
                if mount.get("Destination") == "/var/lib/fmh/media"
                and mount.get("Type") == "volume" and mount.get("RW")]

    if not media_volume("be") or media_volume("be") != media_volume("worker"):
        raise CheckError("API와 worker의 공유 media 볼륨이 일치하지 않습니다.")
    emit("[PASS] API·worker·migration 동일 이미지 / API·worker 공유 media 볼륨")
    return containers


def fixture(docker: Docker, container: str, action: str, run_id: str) -> dict:
    try:
        value = docker.call([
            "exec", "-i", container, "uv", "run", "--no-project", "--no-sync",
            "--no-env-file", "--python", "/usr/local/bin/python", "python", "-", action, run_id,
        ], input_text=(HERE / "fixtures.py").read_text())
    except CheckError as exc:
        raise CheckError(f"테스트 자료 {action}: {exc}") from exc
    try:
        return json.loads(value)
    except (ValueError, TypeError) as exc:
        raise CheckError(f"테스트 자료 {action} 응답이 올바른 JSON이 아닙니다.") from exc


def discover_url(docker: Docker, container: str) -> str:
    ports = docker.call(["port", container, "8000/tcp"]).splitlines()
    for binding in ports:
        host, _, port = binding.rpartition(":")
        if host in ("127.0.0.1", "0.0.0.0", "[::]", "[::1]") and port.isdigit():
            return f"http://localhost:{port}"
    raise CheckError("API 공개 포트를 찾을 수 없습니다. --base-url로 접속 주소를 지정하세요.")


def database_address_matches(server_address: str | None, container_addresses: list[str]) -> bool:
    """마스크 표기와 관계없이 같은 호스트 IP인지 확인한다. 같은 서브넷만으로는 허용하지 않는다."""
    if not isinstance(server_address, str) or not server_address:
        return False
    try:
        server_ip = ip_interface(server_address).ip
        return server_ip in {ip_address(address) for address in container_addresses}
    except ValueError:
        return False


def validate_url(value: str) -> str:
    url = urlsplit(value)
    if (url.scheme not in ("http", "https") or not url.hostname or url.username
            or url.password or url.query or url.fragment):
        raise argparse.ArgumentTypeError("--base-url은 인증정보·query·fragment 없는 HTTP(S) 주소여야 합니다.")
    if url.path.rstrip("/").endswith("/v1"):
        raise argparse.ArgumentTypeError("--base-url에는 /v1을 제외한 서버 주소를 지정하세요.")
    try:
        url.port
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--base-url 포트가 올바르지 않습니다.") from exc
    return value.rstrip("/")


def positive_seconds(value: str) -> float:
    number = float(value)
    if not 0 < number <= 3600:
        raise argparse.ArgumentTypeError("제한 시간은 0초 초과 3600초 이하여야 합니다.")
    return number


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("api", "scenarios"), help="api: 전체 API, scenarios: 기획 흐름")
    parser.add_argument("--project", default="fix-my-home", help="실행 중인 Compose 프로젝트 이름")
    parser.add_argument("--base-url", type=validate_url, help="공개 서버 주소 (/v1 제외); 기본: be 공개 포트")
    parser.add_argument("--output", type=Path, help="결과를 저장할 빈 디렉터리")
    parser.add_argument("--keep-data", action="store_true", help="남은 테스트 자료의 종료 정리를 생략")
    parser.add_argument("--http-timeout", type=positive_seconds, default=20.0)
    parser.add_argument("--poll-timeout", type=positive_seconds, default=180.0)
    args = parser.parse_args(argv)
    if not args.suite:
        if sys.stdin.isatty():
            print("E2E 실행 모드\n  1) 전체 API (api)\n  2) 기획 시나리오 (scenarios)", flush=True)
            try:
                answer = input("선택 [1]: ").strip()
            except EOFError:
                answer = ""
            if answer not in ("", "1", "2", "api", "scenarios"):
                parser.error("1/api 또는 2/scenarios를 선택하세요.")
            args.suite = "scenarios" if answer in ("2", "scenarios") else "api"
        else:
            args.suite = "api"
    return args


def run_http(args, config_path: Path, result_dir: Path, base_url: str, emit) -> int:
    command = [
        "uv", "run", "--no-sync", "--no-env-file", "python", str(HERE / "scenarios.py"),
        "--config", str(config_path), "--output", str(result_dir), "--suite", args.suite,
        "--base-url", base_url, "--http-timeout", str(args.http_timeout),
        "--poll-timeout", str(args.poll_timeout),
    ]
    with subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, bufsize=1) as process:
        try:
            assert process.stdout is not None
            for line in process.stdout:
                emit(line.rstrip("\n"))
            return process.wait()
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise


def execute(args) -> int:
    run_id = "e2e-" + uuid.uuid4().hex
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    result_dir = (args.output or ROOT / ".runtime" / "e2e" / f"{stamp}-{run_id}").resolve()
    if result_dir.exists() and (not result_dir.is_dir() or any(result_dir.iterdir())):
        print("[FAIL] --output은 비어 있는 디렉터리여야 합니다.", file=sys.stderr)
        return 1
    result_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(result_dir, 0o700)
    config_path = result_dir / ".credentials.json"
    report = {"runId": run_id, "suite": args.suite, "status": "FAILED", "cleanup": "NOT_STARTED"}
    docker = Docker()
    cleanup_container = None
    exit_code = 1
    log = (result_dir / "terminal.log").open("w", encoding="utf-8")

    def emit(message):
        print(message, flush=True)
        log.write(message + "\n")
        log.flush()

    try:
        emit(f"E2E | suite={args.suite} | project={args.project} | run={run_id}")
        emit("[환경 확인] 실행 중인 docker-compose.yaml의 DB → migration → API → worker")
        containers = preflight(docker, args.project, emit)
        api_environment = fixture(docker, containers["be"], "check", run_id)
        worker_environment = fixture(docker, containers["worker"], "check", run_id)
        if api_environment != worker_environment:
            raise CheckError("API와 worker의 DB·환경·Origin·AI 설정이 일치하지 않습니다.")
        database_addresses = docker.call([
            "inspect", "--format",
            '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{"\\n"}}{{end}}',
            containers["db"],
        ]).split()
        if not database_address_matches(api_environment.get("databaseServerAddress"), database_addresses):
            raise CheckError("API와 worker가 Compose db 컨테이너의 PostgreSQL에 연결되어 있지 않습니다.")
        if api_environment.get("storageDir") != "/var/lib/fmh/media":
            raise CheckError("API와 worker의 저장 경로가 공유 media 볼륨 경로와 다릅니다.")
        emit("[PASS] API·worker PostgreSQL 17 연결 / schema / 개발 환경 / 설정 일치")
        base_url = args.base_url or discover_url(docker, containers["be"])
        report["baseUrl"] = base_url
        report["containers"] = containers
        emit(f"[대상] {base_url} | AI 작업 기대 결과: {api_environment['aiExpectedStatus']}")
        emit("[자료 준비] 실행 전용 계정·사진·지역·기사 일정 기준 자료")
        # prepare 중 일부 작업이 실패하더라도 이 실행 ID의 자료를 회수한다.
        cleanup_container = containers["be"]
        config = fixture(docker, cleanup_container, "prepare", run_id)
        with config_path.open("x", encoding="utf-8") as output:
            os.chmod(config_path, 0o600)
            json.dump(config, output, ensure_ascii=False)
        emit("[PASS] 자료 준비 완료; 실제 HTTP 테스트 시작")
        exit_code = run_http(args, config_path, result_dir, base_url, emit)
        if exit_code < 0:
            exit_code = 128 - exit_code
        report["status"] = "PASSED" if exit_code == 0 else "FAILED"
        if exit_code:
            summary_path = result_dir / "summary.json"
            if summary_path.is_file():
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                if isinstance(summary.get("failure"), str):
                    report["error"] = summary["failure"]
    except KeyboardInterrupt:
        emit("[FAIL] 사용자가 실행을 중단했습니다.")
        report["error"] = "INTERRUPTED"
        exit_code = 130
    except (CheckError, ValueError, OSError) as exc:
        message = str(exc) if isinstance(exc, CheckError) else f"실행 오류 ({type(exc).__name__})"
        emit(f"[FAIL] {message}")
        report["error"] = message
        exit_code = 1
    finally:
        if cleanup_container:
            if args.keep_data:
                report["cleanup"] = "KEPT"
                emit(f"[정리 보류] --keep-data 지정: {run_id}")
            else:
                emit("[자료 정리] 이번 실행에서 만든 자료만 삭제")
                try:
                    fixture(docker, cleanup_container, "cleanup", run_id)
                    report["cleanup"] = "PASSED"
                    emit("[PASS] 테스트 자료 정리 완료")
                except (CheckError, ValueError, OSError, KeyboardInterrupt):
                    report["cleanup"] = "FAILED"
                    report["status"] = "FAILED"
                    emit(f"[FAIL] 자료 정리 실패. 보존된 실행 ID: {run_id}")
                    if exit_code == 0:
                        exit_code = 1
        config_path.unlink(missing_ok=True)
        report["exitCode"] = exit_code
        (result_dir / "run-result.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        if report.get("error"):
            emit(f"[실패 원인] {report['error']}")
        emit(f"[최종 결과] {report['status']} | 정리={report['cleanup']} | 결과: {result_dir}")
        log.close()
    return exit_code


def main(argv=None) -> int:
    args = parse_args(argv)
    return execute(args)


if __name__ == "__main__":
    def interrupt(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    raise SystemExit(main())
