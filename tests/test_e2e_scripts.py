"""Bash 시나리오 전체를 실제 앱/worker에 연결한다. TCP 사용은 필요하지 않다.

curl만 FIFO 어댑터로 교체하고 요청·파일·역할·응답은 FastAPI에 그대로 전달한다.
실제 curl/TCP/TLS 동작은 scripts/e2e/run.sh --local 또는 --config로 확인한다.
"""

import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from app.contract_data import ENDPOINTS
from app.errors import DomainError
from app.worker import run_once
from conftest import APIClient
from scripts.e2e.fixtures import prepare, write_json
from scripts.e2e.local import diagnosis, find_font

ROOT = Path(__file__).resolve().parents[1]


def curl_request(arguments, clients, app):
    """이 시나리오에서 사용하는 curl 인자를 HTTP 요청으로 옮긴다."""
    method, headers, fields, files = "GET", {}, {}, []
    body = None
    cookie = cookie_output = output = header_file = url = None
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        index += 1
        if argument in ("-q", "--silent", "--show-error", "--globoff"):
            continue
        if not argument.startswith("-"):
            url = argument
            continue
        value = arguments[index]
        index += 1
        if argument == "--request":
            method = value
        elif argument == "--header":
            key, content = value.split(":", 1)
            headers[key] = content.strip()
        elif argument == "--output":
            output = value
        elif argument == "--dump-header":
            header_file = value
        elif argument == "--cookie":
            cookie = value
        elif argument == "--cookie-jar":
            cookie_output = value
        elif argument == "--data-binary":
            assert value.startswith("@")
            body = Path(value[1:]).read_bytes()
        elif argument == "--form-string":
            key, content = value.split("=", 1)
            fields[key] = content
        elif argument == "--form":
            key, content = value.split("=@", 1)
            source, filename, mime = content.split(";")
            files.append((key, (
                filename.removeprefix("filename="),
                Path(source.strip('"')).read_bytes(), mime.removeprefix("type="),
            )))
        else:
            assert argument in (
                "--write-out", "--connect-timeout", "--max-time",
            ), argument
    assert url and output and header_file
    if cookie not in clients:
        clients[cookie] = APIClient(app)
        clients[cookie].__enter__()
    client = clients[cookie]
    client.cookies.clear()
    if cookie is not None:
        assert cookie_output == cookie
        stored_cookies = MozillaCookieJar(cookie)
        if Path(cookie).exists():
            stored_cookies.load(ignore_discard=True, ignore_expires=True)
            client.cookies.update(stored_cookies)
    parsed = urlsplit(url)
    path = parsed.path + ("?" + parsed.query if parsed.query else "")
    response = client.request(
        method, path, headers=headers, content=body,
        data=fields or None, files=files or None, follow_redirects=False,
    )
    if cookie_output:
        stored_cookies = MozillaCookieJar(cookie_output)
        for item in client.cookies.jar:
            stored_cookies.set_cookie(item)
        stored_cookies.save(ignore_discard=True, ignore_expires=True)
    Path(output).write_bytes(response.content)
    Path(header_file).write_text(
        f"HTTP/1.1 {response.status_code}\r\n"
        + "".join(f"{key}: {value}\r\n" for key, value in response.headers.items()),
    )
    return response.status_code


@dataclass
class BashResult:
    process: subprocess.CompletedProcess
    directory: Path
    requests: list
    passwords: list

    @property
    def summary(self):
        return json.loads((self.directory / "summary.json").read_text())

    @property
    def coverage(self):
        return json.loads((self.directory / "coverage.json").read_text())

    @property
    def diagnostic(self):
        last = self.directory / "last-response"
        return last.read_text(errors="replace") if last.exists() else ""

    def assert_success(self):
        assert self.process.returncode == 0, (
            self.process.stdout[-6000:] + self.process.stderr + self.diagnostic
        )
        assert self.summary["passed"]

    def assert_credentials_removed(self):
        for name in ("cookies", "response-headers", "request-body.json"):
            assert not (self.directory / name).exists()
        artifacts = self.process.stdout + self.process.stderr
        for path in self.directory.rglob("*"):
            if path.is_file():
                artifacts += path.read_text(errors="replace")
        for password in self.passwords:
            assert password not in artifacts
            assert json.dumps(password, ensure_ascii=False)[1:-1] not in artifacts
            assert json.dumps(password, ensure_ascii=True)[1:-1] not in artifacts


@pytest.fixture
def bash_e2e(environment, tmp_path):
    """실제 앱에 연결되는 Bash 실행기를 다른 로그인 테스트에서도 공유한다."""
    if any(shutil.which(command) is None for command in ("bash", "jq", "curl")):
        pytest.skip("Bash E2E 검증에는 bash, jq, curl이 필요합니다.")
    settings, factory, app = environment
    try:
        settings.pdf_font = find_font()
    except RuntimeError:
        pytest.skip("PDF 한글 폰트가 필요합니다.")
    fixtures = tmp_path / "fixtures"
    config = prepare(settings, factory, fixtures, "http://testserver/v1")
    incoming, outgoing = tmp_path / "incoming", tmp_path / "outgoing"
    os.mkfifo(incoming)
    os.mkfifo(outgoing)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    proxy = binaries / "curl"
    proxy.write_text(
        '#!/usr/bin/env bash\nset -euo pipefail\n'
        "jq -cn --args '$ARGS.positional' -- \"$@\" > \"$E2E_RPC_IN\"\n"
        'IFS= read -r status < "$E2E_RPC_OUT"\n'
        'printf "%s" "$status"\n'
    )
    proxy.chmod(0o700)
    child_env = {
        key: value for key, value in os.environ.items()
        if not key.startswith("E2E_")
    }
    child_env.update({
        "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
        "E2E_RPC_IN": str(incoming), "E2E_RPC_OUT": str(outgoing),
    })

    def run(*options, stdin="", ai_mode="success"):
        if ai_mode == "expected_failure":
            config["ai"] = {"expectedStatus": "FAILED", "expectedErrorCode": "AI_NOT_CONFIGURED"}
        write_json(fixtures / "config.json", config)
        failures, requests, passwords, clients = [], [], [], {}
        stopped = threading.Event()

        def provider(*args):
            if ai_mode == "success":
                return diagnosis(*args)
            raise DomainError("AI_NOT_CONFIGURED", "테스트용 AI 미설정 상태", 503)

        def serve():
            try:
                while not stopped.is_set():
                    with incoming.open() as stream:
                        payload = stream.read()
                    if not payload:
                        continue
                    arguments = json.loads(payload)
                    if arguments is None:
                        break
                    try:
                        method = arguments[arguments.index("--request") + 1]
                        path = urlsplit(arguments[-1]).path
                        requests.append((method, path))
                        if path in ("/v1/auth/login", "/v1/auth/signup"):
                            body_file = arguments[arguments.index("--data-binary") + 1][1:]
                            password = json.loads(Path(body_file).read_text())["password"]
                            if len(password) >= 12:
                                passwords.append(password)
                        status = curl_request(arguments, clients, app)
                        # 첫 AI polling에서 QUEUED를 읽도록 실제 worker 실행을 한 번 미룬다.
                        if not (method == "POST" and arguments[-1].endswith("/ai-jobs")):
                            while run_once(factory, settings, provider=provider):
                                pass
                    except Exception as error:
                        failures.append(error)
                        status = 599
                    with outgoing.open("w") as stream:
                        stream.write(f"{status}\n")
            finally:
                for client in clients.values():
                    client.__exit__(None, None, None)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        output = tmp_path / "results"
        try:
            process = subprocess.run(
                ["bash", str(ROOT / "scripts/e2e/run.sh"),
                 "--config", str(fixtures / "config.json"), "--output", str(output), *options],
                cwd=tmp_path, env=child_env, input=stdin,
                capture_output=True, text=True, timeout=120,
            )
        finally:
            stopped.set()
            # reader가 기다리는 중에도 TCP 없이 종료한다.
            try:
                descriptor = os.open(incoming, os.O_WRONLY | os.O_NONBLOCK)
            except OSError:
                descriptor = None
            if descriptor is not None:
                os.write(descriptor, b"null\n")
                os.close(descriptor)
            thread.join(timeout=10)
        assert not thread.is_alive(), "curl FIFO 어댑터가 종료되지 않았습니다."
        assert not failures, failures
        directories = list(output.glob("run.*"))
        assert len(directories) == 1, process.stdout + process.stderr
        return BashResult(process, directories[0], requests, passwords)

    return config, run


@pytest.mark.parametrize("ai_mode", ["success", "expected_failure", "unexpected_failure"])
def test_bash_scenarios_cover_every_endpoint(bash_e2e, ai_mode):
    _, run = bash_e2e
    result = run(ai_mode=ai_mode)
    result.assert_credentials_removed()
    summary = result.summary
    if ai_mode == "unexpected_failure":
        assert result.process.returncode != 0 and not summary["passed"]
        assert "예상 종료 상태 SUCCEEDED, 실제 FAILED" in result.process.stderr
        assert json.loads(result.diagnostic)["data"]["error"]["code"] == "AI_NOT_CONFIGURED"
        return
    result.assert_success()
    report = result.coverage
    assert report["total"] == len(ENDPOINTS)
    assert report["successful"] == len(ENDPOINTS) - 1
    assert report["missing"] == ["POST /auth/signup"]
    assert [item["endpoint"] for item in report["skipped"]] == ["POST /auth/signup"]
    assert all(item["reason"] for item in report["skipped"])
    assert report["uncovered"] == []
    assert summary["passed"] and summary["assertions"] > len(ENDPOINTS)
