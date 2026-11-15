"""Docker CLI가 저장한 Docker Hub 자격 증명을 읽기 전용으로 가져온다.

실제 파일 접근은 사용자가 조회 도구를 실행할 때만 수행한다.
비밀번호·토큰과 credential helper의 출력은 화면이나 오류에 포함하지 않는다.
"""

import base64
import binascii
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

HUB_SERVERS = (
    "https://index.docker.io/v1/",
    "https://index.docker.io/v1",
    "docker.io",
    "https://docker.io",
    "index.docker.io",
    "https://index.docker.io",
    "registry-1.docker.io",
    "https://registry-1.docker.io",
)
HELPER_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
MISSING_CREDENTIAL = "credentials not found in native keychain"


class DockerCredentialError(Exception):
    """자격 증명과 외부 프로그램 출력을 담지 않는 오류."""


@dataclass(frozen=True, repr=False)
class DockerCredentials:
    username: str = ""
    password: str = ""
    identity_token: str = ""


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise DockerCredentialError("Docker 로그인 정보의 형식이 올바르지 않습니다.")
    return value


def _helper_credentials(helper: str, server: str) -> DockerCredentials | None:
    if not HELPER_NAME.fullmatch(helper):
        raise DockerCredentialError("Docker credential helper 설정을 확인하세요.")
    try:
        result = subprocess.run(
            [f"docker-credential-{helper}", "get"],
            input=server,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            check=False,
        )
    except (OSError, UnicodeError, subprocess.SubprocessError):
        raise DockerCredentialError(
            "Docker credential helper를 실행할 수 없습니다. Docker 로그인 설정을 확인하세요."
        ) from None

    if result.returncode:
        # Docker의 표준 '저장된 자격 증명 없음' 응답만 익명 조회로 이어진다.
        if any(
            output.strip().lower() == MISSING_CREDENTIAL
            for output in (result.stdout, result.stderr)
        ):
            return None
        raise DockerCredentialError(
            "Docker credential helper에서 로그인 정보를 가져오지 못했습니다."
        )
    try:
        payload = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        raise DockerCredentialError("Docker credential helper 응답 형식이 올바르지 않습니다.") from None
    if not isinstance(payload, dict):
        raise DockerCredentialError("Docker credential helper 응답 형식이 올바르지 않습니다.")
    username = _string(payload.get("Username", ""))
    secret = _string(payload.get("Secret", ""))
    if not username and not secret:
        return None
    if not username or not secret:
        raise DockerCredentialError("Docker credential helper의 로그인 정보가 불완전합니다.")
    if username == "<token>":
        return DockerCredentials(identity_token=secret)
    return DockerCredentials(username=username, password=secret)


def _inline_credentials(entry: dict) -> DockerCredentials | None:
    identity_token = _string(entry.get("identitytoken", ""))
    if identity_token:
        return DockerCredentials(identity_token=identity_token)
    encoded = _string(entry.get("auth", ""))
    if not encoded:
        return None
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (ValueError, binascii.Error, UnicodeError):
        raise DockerCredentialError("Docker 로그인 정보의 인코딩이 올바르지 않습니다.") from None
    username, separator, password = decoded.partition(":")
    if not separator or not username or not password:
        raise DockerCredentialError("Docker 로그인 정보가 불완전합니다. docker login을 확인하세요.")
    return DockerCredentials(username=username, password=password)


def load_docker_credentials(
    config_directory: Path | None = None,
) -> DockerCredentials | None:
    """credHelpers, credsStore, 파일 auths 순서로 Hub 로그인 정보를 선택한다."""
    if config_directory is None:
        configured_directory = os.environ.get("DOCKER_CONFIG")
        config_directory = (
            Path(configured_directory) if configured_directory else Path.home() / ".docker"
        )
    path = config_directory / "config.json"
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, UnicodeError):
        raise DockerCredentialError("Docker 설정 파일을 읽을 수 없습니다. 형식과 권한을 확인하세요.") from None
    if not isinstance(config, dict):
        raise DockerCredentialError("Docker 설정 파일의 형식이 올바르지 않습니다.")

    helpers = config.get("credHelpers")
    auths = config.get("auths")
    helpers = {} if helpers is None else helpers
    auths = {} if auths is None else auths
    if not isinstance(helpers, dict) or not isinstance(auths, dict):
        raise DockerCredentialError("Docker 로그인 설정의 형식이 올바르지 않습니다.")

    # CLI는 Hub 정규 키만 helper 선택에 사용한다. 명시적인 빈 helper는
    # 공통 credsStore도 사용하지 않고 파일 인증을 선택한다는 뜻이다.
    server = HUB_SERVERS[0]
    if server in helpers:
        helper = _string(helpers[server])
    else:
        store = config.get("credsStore")
        helper = "" if store is None else _string(store)
    if helper:
        return _helper_credentials(helper, server)

    for server in HUB_SERVERS:
        if server in auths:
            entry = auths[server]
            if not isinstance(entry, dict):
                raise DockerCredentialError("Docker Hub 로그인 설정의 형식이 올바르지 않습니다.")
            credentials = _inline_credentials(entry)
            if credentials is not None:
                return credentials
    return None
