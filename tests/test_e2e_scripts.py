"""Bash 시나리오 전체를 실제 앱/worker에 연결한다. TCP 사용은 필요하지 않다.

curl만 FIFO 어댑터로 교체하고 요청·파일·역할·응답은 FastAPI에 그대로 전달한다.
실제 curl/TCP/TLS 동작은 scripts/e2e/run.sh --local 또는 --config로 확인한다.
"""

import json
import os
import shutil
import subprocess
import threading
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


@pytest.mark.parametrize("ai_mode", ["success", "expected_failure", "unexpected_failure"])
def test_bash_scenarios_cover_every_endpoint(environment, tmp_path, ai_mode):
    if any(shutil.which(command) is None for command in ("bash", "jq", "curl")):
        pytest.skip("Bash E2E 검증에는 bash, jq, curl이 필요합니다.")
    settings, factory, app = environment
    try:
        settings.pdf_font = find_font()
    except RuntimeError:
        pytest.skip("PDF 한글 폰트가 필요합니다.")
    fixtures = tmp_path / "fixtures"
    config = prepare(settings, factory, fixtures, "http://testserver/v1")
    if ai_mode == "expected_failure":
        config["ai"] = {"expectedStatus": "FAILED", "expectedErrorCode": "AI_NOT_CONFIGURED"}
        write_json(fixtures / "config.json", config)

    def provider(*args):
        if ai_mode == "success":
            return diagnosis(*args)
        raise DomainError("AI_NOT_CONFIGURED", "테스트용 AI 미설정 상태", 503)
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
    failures = []
    stopped = threading.Event()
    clients = {}

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
                    status = curl_request(arguments, clients, app)
                    # 실제 worker를 통해 비동기 작업을 완료한다. AI 제공자만 고정한다.
                    # 첫 AI polling은 QUEUED를 읽도록 해 대기 분기도 실행한다.
                    if not ("POST" in arguments and arguments[-1].endswith("/ai-jobs")):
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
    child_env = {
        key: value for key, value in os.environ.items()
        if not key.startswith("E2E_")
    }
    child_env.update({
        "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
        "E2E_RPC_IN": str(incoming), "E2E_RPC_OUT": str(outgoing),
    })
    try:
        result = subprocess.run(
            ["bash", str(ROOT / "scripts/e2e/run.sh"), "--config", str(fixtures / "config.json"),
             "--output", str(tmp_path / "results")],
            cwd=tmp_path, env=child_env, capture_output=True, text=True, timeout=120,
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
    assert not failures, failures
    run = next((tmp_path / "results").glob("run.*"))
    last = run / "last-response"
    diagnostic = last.read_text(errors="replace") if last.exists() else ""
    assert not (run / "cookies").exists()
    assert not (run / "response-headers").exists()
    assert not (run / "request-body.json").exists()
    summary = json.loads((run / "summary.json").read_text())
    if ai_mode == "unexpected_failure":
        assert result.returncode != 0 and not summary["passed"]
        assert "예상 종료 상태 SUCCEEDED, 실제 FAILED" in result.stderr
        assert json.loads(diagnostic)["data"]["error"]["code"] == "AI_NOT_CONFIGURED"
        return
    assert result.returncode == 0, result.stdout[-6000:] + result.stderr + diagnostic
    report = json.loads((run / "coverage.json").read_text())
    assert report["successful"] == report["total"] == len(ENDPOINTS)
    assert report["missing"] == []
    assert summary["passed"] and summary["assertions"] > len(ENDPOINTS)
