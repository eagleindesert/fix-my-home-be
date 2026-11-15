"""Docker CLI 로그인으로 Docker Hub Registry의 태그를 조회한다.

자격 증명은 토큰 교환에만 사용하며 파일·화면·오류 메시지에 기록하지 않는다.
표준 라이브러리만 사용하고 .env를 읽지 않는다.
"""

import argparse
import base64
import json
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

if __package__:
    from .docker_credentials import (
        DockerCredentialError,
        DockerCredentials,
        load_docker_credentials,
    )
else:
    from docker_credentials import (
        DockerCredentialError,
        DockerCredentials,
        load_docker_credentials,
    )

REGISTRY_ORIGIN = "https://registry-1.docker.io"
TOKEN_URL = "https://auth.docker.io/token"
TAG_PATTERN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}")
REPOSITORY_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]*/[a-z0-9][a-z0-9._-]*")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        # 인증 헤더와 refresh token이 리다이렉트 대상으로 전달되지 않게 한다.
        return None


urlopen = build_opener(NoRedirect()).open


class HubLookupError(Exception):
    """응답 본문이나 인증 정보를 포함하지 않는 조회 오류."""


class HubNotFoundError(HubLookupError):
    """첫 태그 조회에서만 아직 이미지가 없는 상태로 처리할 수 있는 404 응답."""


def repository_name(image_name: str) -> str:
    if image_name.startswith("localhost/"):
        raise HubLookupError("Docker Hub 이미지 이름을 namespace/repository 형식으로 지정하세요.")
    for prefix in ("docker.io/", "index.docker.io/"):
        if image_name.startswith(prefix):
            image_name = image_name.removeprefix(prefix)
            break
    if not REPOSITORY_PATTERN.fullmatch(image_name):
        raise HubLookupError("Docker Hub 이미지 이름을 namespace/repository 형식으로 지정하세요.")
    return image_name


def read_json(request: Request, *, authentication: bool = False) -> tuple[dict, str]:
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read())
            link = response.headers.get("Link", "")
    except HTTPError as error:
        if error.code in (400, 401, 403) and authentication:
            message = "Docker 로그인 인증에 실패했습니다. 같은 사용자로 docker login을 다시 실행하세요."
        elif error.code in (401, 403):
            message = "로그인 계정의 저장소 읽기 권한과 IMAGE_NAME을 확인하세요."
        elif error.code == 404:
            raise HubNotFoundError("Docker Hub 조회 대상을 찾을 수 없습니다 (HTTP 404).") from None
        elif error.code == 429:
            message = "Docker Hub 호출 제한에 도달했습니다. 잠시 후 다시 실행하세요."
        else:
            message = f"Docker Hub가 HTTP {error.code} 오류를 반환했습니다."
        raise HubLookupError(message) from None
    except (URLError, OSError):
        raise HubLookupError("Docker Hub에 연결할 수 없습니다. 네트워크를 확인하세요.") from None
    except (ValueError, UnicodeError):
        raise HubLookupError("Docker Hub 응답 또는 인증 정보의 형식이 올바르지 않습니다.") from None
    if not isinstance(payload, dict):
        raise HubLookupError("Docker Hub 응답 형식이 올바르지 않습니다.")
    return payload, link


def registry_token(repository: str, credentials: DockerCredentials | None) -> str:
    fields = {
        "service": "registry.docker.io",
        "scope": f"repository:{repository}:pull",
        "client_id": "docker",
    }
    headers = {"Accept": "application/json", "User-Agent": "fix-my-home-build-push"}
    if credentials and credentials.identity_token:
        # Docker IdentityToken은 Registry의 refresh token 교환 방식으로 인증한다.
        fields.update(grant_type="refresh_token", refresh_token=credentials.identity_token)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = Request(TOKEN_URL, data=urlencode(fields).encode(), headers=headers)
    else:
        if credentials and credentials.username:
            fields["account"] = credentials.username
            basic = base64.b64encode(
                f"{credentials.username}:{credentials.password}".encode()
            ).decode("ascii")
            headers["Authorization"] = f"Basic {basic}"
        request = Request(f"{TOKEN_URL}?{urlencode(fields)}", headers=headers)
    payload, _ = read_json(request, authentication=True)
    token = payload.get("token") or payload.get("access_token")
    if not isinstance(token, str) or not token or "\r" in token or "\n" in token:
        raise HubLookupError("Docker Hub 인증 응답에 유효한 접근 토큰이 없습니다.")
    return token


def next_page_url(link: str, current_url: str, path: str) -> str | None:
    if not link:
        return None
    next_url = None
    for part in link.split(","):
        entry = re.fullmatch(r"\s*<([^<>]+)>\s*(.*)", part)
        relation = re.search(r';\s*rel\s*=\s*(?:"([^"]+)"|([^;\s]+))', part)
        if entry is None or relation is None:
            raise HubLookupError("Docker Hub의 다음 페이지 정보가 올바르지 않습니다.")
        if "next" not in (relation[1] or relation[2]).split():
            continue
        if next_url is not None:
            raise HubLookupError("Docker Hub의 다음 페이지 정보가 중복되었습니다.")
        try:
            next_url = urljoin(current_url, entry[1])
            target = urlsplit(next_url)
        except ValueError:
            raise HubLookupError("Docker Hub의 다음 페이지 주소가 올바르지 않습니다.") from None
        if (target.scheme != "https" or target.netloc != "registry-1.docker.io"
                or target.path != path or target.fragment):
            raise HubLookupError("Docker Hub의 다음 페이지 주소가 올바르지 않습니다.")
    return next_url


def list_tags(image_name: str) -> list[str]:
    repository = repository_name(image_name)
    try:
        credentials = load_docker_credentials()
    except DockerCredentialError as error:
        raise HubLookupError(str(error)) from None
    token = registry_token(repository, credentials)
    path = f"/v2/{repository}/tags/list"
    url = f"{REGISTRY_ORIGIN}{path}?n=100"
    visited = set()
    tags = set()
    while url:
        if url in visited:
            raise HubLookupError("Docker Hub의 페이지가 반복되어 태그 조회를 중단했습니다.")
        visited.add(url)
        request = Request(url, headers={
            "Accept": "application/json",
            "User-Agent": "fix-my-home-build-push",
            "Authorization": f"Bearer {token}",
        })
        try:
            page, link = read_json(request)
        except HubNotFoundError:
            # 첫 푸시 전에는 태그 API가 404를 반환할 수 있다. 인증 요청이나
            # 후속 페이지의 404까지 빈 저장소로 처리하면 조회 실패를 숨기게 된다.
            if len(visited) == 1:
                return []
            raise
        names = page.get("tags")
        if (page.get("name") != repository or "tags" not in page
                or (names is not None and not isinstance(names, list))):
            raise HubLookupError("Docker Hub 태그 목록의 응답 형식이 올바르지 않습니다.")
        for name in names or []:
            if not isinstance(name, str) or not TAG_PATTERN.fullmatch(name):
                raise HubLookupError("Docker Hub 태그 이름의 형식이 올바르지 않습니다.")
            tags.add(name)
        url = next_page_url(link, url, path)
        if url and not names:
            raise HubLookupError("Docker Hub의 빈 페이지에 다음 페이지가 지정되어 있습니다.")
    return sorted(tags)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Docker CLI 로그인으로 Docker Hub 태그를 조회합니다.")
    parser.add_argument("image", help="Docker Hub 이미지 이름: namespace/repository")
    args = parser.parse_args(argv)
    repository = ""
    try:
        repository = repository_name(args.image)
        tags = list_tags(repository)
    except HubLookupError as error:
        target = f" ({repository})" if repository else ""
        print(f"Docker Hub 태그 조회 실패{target}: {error}", file=sys.stderr)
        return 1

    print(f"Docker Hub 기존 태그 ({repository}, {len(tags)}개, 이름순):")
    if tags:
        for tag in tags:
            print(f"  {tag}")
    else:
        print("  등록된 이미지가 없습니다. 첫 버전을 지정할 수 있습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
