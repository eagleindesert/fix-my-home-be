"""배포 서버용 계정 선택과 셸 비밀번호 입력을 실제 API에 연결해 검증한다."""

import json
import os
import pty
import select
import shutil
import subprocess
import termios
import time

import pytest
from sqlalchemy import select as sql_select

from app.db import Account
from app.security import hash_password
from test_e2e_scripts import ROOT, bash_e2e  # noqa: F401 — 다른 모듈의 pytest fixture


def credentials_input(accounts):
    return "".join(
        f'{accounts[actor]["loginId"]}\n{accounts[actor]["password"]}\n'
        for actor in ("user", "other", "technician")
    )


def test_interactive_random_signup_runs_without_config_credentials(bash_e2e, environment):
    config, run = bash_e2e
    config.pop("accounts")
    _, factory, _ = environment
    with factory() as db:
        previous_ids = set(db.scalars(sql_select(Account.id)))

    result = run("--interactive", "--skip-health", stdin="1\n")
    result.assert_success()
    result.assert_credentials_removed()
    assert result.summary["loginMode"] == "random"
    assert result.requests.count(("POST", "/v1/auth/signup")) == 3
    assert not any(path.startswith("/health/") for _, path in result.requests)
    report = result.coverage
    assert report["successful"] == report["total"] - 1
    assert report["missing"] == ["POST /deletion-jobs/{jobId}/retry"]
    assert [item["endpoint"] for item in report["skipped"]] == report["missing"]
    assert report["skipped"][0]["reason"]
    assert report["uncovered"] == []
    assert {"endpoint": "POST /deletion-jobs/{jobId}/retry", "status": 409} in report["expectedErrors"]
    # 다른 계정의 실패 삭제 작업 ID가 설정에 남아 있어도 랜덤 모드에서는 쓰지 않는다.
    assert not any(config["failedDeletionJobId"] in path for _, path in result.requests)
    with factory() as db:
        created = list(db.scalars(sql_select(Account).where(Account.id.not_in(previous_ids))))
    assert len(created) == 3
    assert sum("TECHNICIAN" in account.roles for account in created) == 1
    assert all(account.login_id.startswith("e2e-") for account in created)


def test_interactive_existing_accounts_preserve_password_and_normalize_roles(bash_e2e, environment):
    config, run = bash_e2e
    accounts = config.pop("accounts")
    password = '  비밀번호 "작은따옴표\' $HOME $(whoami) \\ 끝  '
    accounts["user"]["password"] = password
    _, factory, _ = environment
    with factory() as db, db.begin():
        account = db.scalar(sql_select(Account).where(Account.login_id == accounts["user"]["loginId"]))
        account.password_hash = hash_password(password)
        # TECHNICIAN이 첫 역할인 기존 사용자도 USER로 맞춘 후 시나리오를 진행한다.
        account.roles = ["TECHNICIAN", "USER"]
    entered = credentials_input(accounts)
    # 잘못된 메뉴 번호와 빈 ID/비밀번호는 다시 입력받는다.
    entered = entered.replace(accounts["user"]["loginId"] + "\n", "\n" + accounts["user"]["loginId"] + "\n\n", 1)
    result = run("--interactive", stdin="9\n2\n" + entered)
    result.assert_success()
    result.assert_credentials_removed()
    assert password in result.passwords
    assert result.summary["loginMode"] == "prompt"
    assert "1 또는 2" in result.process.stderr
    assert ("POST", "/v1/auth/signup") not in result.requests
    assert result.coverage["missing"] == ["POST /auth/signup"]
    assert result.coverage["uncovered"] == []
    recorded_accounts = json.loads((result.directory / "accounts.json").read_text())
    assert {entry["loginId"] for entry in recorded_accounts.values()} == {
        account["loginId"] for account in accounts.values()
    }
    assert all("password" not in entry for entry in recorded_accounts.values())


def test_duplicate_accounts_fail_before_changing_technician_profile(bash_e2e):
    config, run = bash_e2e
    accounts = config.pop("accounts")
    accounts["other"] = accounts["user"]
    result = run("--prompt-login", stdin=credentials_input(accounts))
    assert result.process.returncode != 0
    assert not result.summary["passed"]
    assert "서로 다른" in result.process.stderr
    assert not any(path.startswith("/v1/technicians/me") for _, path in result.requests)
    assert ("POST", "/v1/requests") not in result.requests
    result.assert_credentials_removed()


def test_mismatched_location_fails_before_changing_technician_data(bash_e2e):
    config, run = bash_e2e
    accounts = config.pop("accounts")
    config["locationId"] = "different-from-technician-location"
    result = run("--prompt-login", stdin=credentials_input(accounts))
    assert result.process.returncode != 0
    assert not result.summary["passed"]
    assert "기사 대표 위치 사전 자료" in result.process.stderr
    assert ("GET", "/v1/technicians/me/schedule") in result.requests
    for mutation in (
        ("POST", "/v1/technicians/me/portfolio-photos"),
        ("PUT", "/v1/technicians/me/profile"),
        ("POST", "/v1/technicians/me/cases"),
        ("PUT", "/v1/technicians/me/schedule"),
    ):
        assert mutation not in result.requests
    result.assert_credentials_removed()


@pytest.mark.parametrize(
    ("option", "entered"),
    [("--interactive", ""), ("--prompt-login", ""), ("--prompt-login", "some-user\n")],
)
def test_ended_input_fails_without_hanging_or_retaining_secrets(bash_e2e, option, entered):
    config, run = bash_e2e
    config.pop("accounts")
    result = run(option, stdin=entered)
    assert result.process.returncode != 0
    assert not result.summary["passed"]
    assert "입력이 종료" in result.process.stderr
    assert ("POST", "/v1/requests") not in result.requests
    result.assert_credentials_removed()


def test_incorrect_password_stops_and_cleans_up(bash_e2e):
    config, run = bash_e2e
    accounts = config.pop("accounts")
    accounts["user"]["password"] = "incorrect-secret-password"
    result = run("--prompt-login", stdin=credentials_input(accounts))
    assert result.process.returncode != 0
    assert not result.summary["passed"]
    assert "INVALID_CREDENTIALS" in result.process.stderr
    assert result.summary["lastRequest"] == "POST /auth/login"
    # 익명 오류 계약 검증 1회와 입력 계정 검증 1회만 한다. 다른 계정 입력으로 넘어가지 않는다.
    assert result.requests.count(("POST", "/v1/auth/login")) == 2
    result.assert_credentials_removed()


def test_password_is_not_echoed_on_a_terminal(tmp_path):
    if any(shutil.which(command) is None for command in ("bash", "jq")):
        pytest.skip("셸 로그인 검증에는 bash와 jq가 필요합니다.")
    master, slave = pty.openpty()
    credentials_file = tmp_path / "entered.json"
    process = subprocess.Popen(
        ["bash", "-euc", 'source "$1"; prompt_credentials user > "$2"', "test-login",
         str(ROOT / "scripts/e2e/lib.sh"), str(credentials_file)],
        stdin=slave, stdout=subprocess.PIPE, stderr=slave,
    )
    terminal_output = bytearray()

    def read_until(text):
        deadline = time.monotonic() + 5
        while text.encode() not in terminal_output:
            remaining = deadline - time.monotonic()
            assert remaining > 0, terminal_output.decode(errors="replace")
            ready, _, _ = select.select([master], [], [], remaining)
            assert ready, terminal_output.decode(errors="replace")
            terminal_output.extend(os.read(master, 4096))

    try:
        read_until("로그인 ID: ")
        os.write(master, b"terminal-user\n")
        read_until("비밀번호: ")
        # 프롬프트 출력 직후 read -s가 TTY echo를 끌 때까지 기다린다.
        deadline = time.monotonic() + 5
        while termios.tcgetattr(slave)[3] & termios.ECHO:
            assert time.monotonic() < deadline, "비밀번호 입력 중 터미널 echo가 켜져 있습니다."
            time.sleep(0.005)
        password = "terminal-only-secret-123"
        os.write(master, (password + "\n").encode())
        stdout, _ = process.communicate(timeout=5)
        while select.select([master], [], [], 0)[0]:
            terminal_output.extend(os.read(master, 4096))
        assert process.returncode == 0
        assert password.encode() not in terminal_output + stdout
        assert json.loads(credentials_file.read_text()) == {
            "loginId": "terminal-user", "password": password,
        }
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        os.close(master)
        os.close(slave)
        credentials_file.unlink(missing_ok=True)
