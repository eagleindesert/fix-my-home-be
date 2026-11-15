import base64
import io
import json
from email.message import Message
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest

from scripts.etc import docker_hub_tags as hub


IMAGE = "eagleindesert/fix-my-home-be"
AUTH_ORIGIN = "https://auth.docker.io"
REGISTRY_ORIGIN = "https://registry-1.docker.io"
TAGS_PATH = f"/v2/{IMAGE}/tags/list"
TAGS_URL = f"{REGISTRY_ORIGIN}{TAGS_PATH}?n=100"
SECOND_PAGE = f"{TAGS_URL}&last=v1"
REGISTRY_TOKEN = "fake-registry-bearer-token"


class FakeResponse:
    def __init__(self, payload, headers=None):
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.headers = Message()
        for name, value in (headers or {}).items():
            self.headers[name] = value

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, *_):
        return self.payload


@pytest.fixture(autouse=True)
def isolated_credentials_and_network(monkeypatch):
    """Tests must never inspect the operator's Docker configuration or contact a server."""
    monkeypatch.setattr(hub, "load_docker_credentials", lambda: None)

    def block_network(*args, **kwargs):
        raise AssertionError("An HTTP response must be explicitly mocked in this test.")

    monkeypatch.setattr(hub, "urlopen", block_network)


def use_credentials(monkeypatch, **values):
    credentials = hub.DockerCredentials(**values)
    monkeypatch.setattr(hub, "load_docker_credentials", lambda: credentials)
    return credentials


def mock_responses(monkeypatch, *responses):
    requests = []
    pending = iter(responses)

    def open_request(request, *, timeout):
        assert timeout == 15
        requests.append(request)
        response = next(pending)
        if isinstance(response, Exception):
            raise response
        return response if isinstance(response, FakeResponse) else FakeResponse(response)

    monkeypatch.setattr(hub, "urlopen", open_request)
    return requests


def assert_token_request(request, account=None):
    target = urlsplit(request.full_url)
    assert f"{target.scheme}://{target.netloc}" == AUTH_ORIGIN
    assert target.path == "/token"
    assert request.get_method() == "GET"
    expected = {
        "service": ["registry.docker.io"],
        "scope": [f"repository:{IMAGE}:pull"],
        "client_id": ["docker"],
    }
    if account:
        expected["account"] = [account]
    assert parse_qs(target.query) == expected


@pytest.mark.parametrize("token_field", ["token", "access_token"])
@pytest.mark.parametrize("empty_credentials", [False, True])
def test_anonymous_lookup_exchanges_a_scoped_token_before_listing_tags(
    monkeypatch, token_field, empty_credentials,
):
    if empty_credentials:
        use_credentials(monkeypatch)
    requests = mock_responses(
        monkeypatch,
        {token_field: REGISTRY_TOKEN},
        {"name": IMAGE, "tags": ["v2", "latest", "v10", "v1"]},
    )

    assert hub.list_tags(IMAGE) == ["latest", "v1", "v10", "v2"]

    assert_token_request(requests[0])
    assert requests[0].get_header("Authorization") is None
    assert requests[1].full_url == TAGS_URL
    assert requests[1].get_header("Authorization") == f"Bearer {REGISTRY_TOKEN}"


def test_docker_login_password_or_pat_is_sent_only_to_the_auth_service(monkeypatch):
    username = "fake-docker-user"
    password = "fake-docker-pat"
    use_credentials(monkeypatch, username=username, password=password)
    requests = mock_responses(
        monkeypatch,
        {"token": REGISTRY_TOKEN},
        {"name": IMAGE, "tags": ["v1"]},
    )

    assert hub.list_tags(IMAGE) == ["v1"]

    assert_token_request(requests[0], account=username)
    basic = base64.b64encode(f"{username}:{password}".encode()).decode()
    assert requests[0].get_header("Authorization") == f"Basic {basic}"
    assert requests[1].get_header("Authorization") == f"Bearer {REGISTRY_TOKEN}"
    assert password not in requests[0].full_url
    assert password not in requests[1].full_url


def test_identity_token_uses_refresh_grant_without_basic_auth(monkeypatch):
    identity_token = "fake-device-login-refresh-token"
    use_credentials(monkeypatch, identity_token=identity_token)
    requests = mock_responses(
        monkeypatch,
        {"access_token": REGISTRY_TOKEN},
        {"name": IMAGE, "tags": ["v1"]},
    )

    assert hub.list_tags(IMAGE) == ["v1"]

    auth = requests[0]
    assert auth.full_url == f"{AUTH_ORIGIN}/token"
    assert auth.get_method() == "POST"
    assert auth.get_header("Content-type") == "application/x-www-form-urlencoded"
    assert auth.get_header("Authorization") is None
    assert parse_qs(auth.data.decode()) == {
        "grant_type": ["refresh_token"],
        "refresh_token": [identity_token],
        "service": ["registry.docker.io"],
        "client_id": ["docker"],
        "scope": [f"repository:{IMAGE}:pull"],
    }
    assert identity_token not in auth.full_url
    assert requests[1].get_header("Authorization") == f"Bearer {REGISTRY_TOKEN}"


@pytest.mark.parametrize("next_link", [SECOND_PAGE, f"{TAGS_PATH}?n=100&last=v1"])
def test_link_pagination_collects_all_tags_before_sorting(monkeypatch, next_link):
    requests = mock_responses(
        monkeypatch,
        {"token": REGISTRY_TOKEN},
        FakeResponse({"name": IMAGE, "tags": ["v1"]}, {"Link": f'<{next_link}>; rel="next"'}),
        {"name": IMAGE, "tags": ["v3", "v2"]},
    )

    assert hub.list_tags(IMAGE) == ["v1", "v2", "v3"]

    assert len(requests) == 3
    assert requests[1].full_url == TAGS_URL
    assert urlsplit(requests[2].full_url).netloc == "registry-1.docker.io"
    assert urlsplit(requests[2].full_url).path == TAGS_PATH
    assert parse_qs(urlsplit(requests[2].full_url).query) == {
        "n": ["100"], "last": ["v1"],
    }
    assert all(
        request.get_header("Authorization") == f"Bearer {REGISTRY_TOKEN}"
        for request in requests[1:]
    )


@pytest.mark.parametrize("image_name", [
    IMAGE,
    f"docker.io/{IMAGE}",
    f"index.docker.io/{IMAGE}",
])
@pytest.mark.parametrize("empty_tags", [None, []])
def test_docker_hub_reference_forms_and_empty_repositories(monkeypatch, image_name, empty_tags):
    requests = mock_responses(
        monkeypatch,
        {"token": REGISTRY_TOKEN},
        {"name": IMAGE, "tags": empty_tags},
    )

    assert hub.list_tags(image_name) == []

    assert_token_request(requests[0])
    assert requests[1].full_url == TAGS_URL


@pytest.mark.parametrize("empty_response", ["not_found", "null", "empty_list"])
def test_missing_or_empty_image_reports_success_for_first_version(
    monkeypatch, capsys, empty_response,
):
    detail = "fake-sensitive-not-found-detail"
    if empty_response == "not_found":
        response = HTTPError(TAGS_URL, 404, detail, {}, io.BytesIO(detail.encode()))
    else:
        response = {"name": IMAGE, "tags": None if empty_response == "null" else []}
    requests = mock_responses(monkeypatch, {"token": REGISTRY_TOKEN}, response)

    assert hub.main([IMAGE]) == 0

    output = capsys.readouterr()
    assert output.err == ""
    assert IMAGE in output.out
    assert "등록된 이미지가 없습니다" in output.out
    assert "첫 버전" in output.out
    assert detail not in output.out
    assert REGISTRY_TOKEN not in output.out
    assert len(requests) == 2
    assert requests[1].full_url == TAGS_URL


@pytest.mark.parametrize("error", [
    HTTPError(TAGS_URL, status, "fake-sensitive-detail", {}, None)
    for status in (401, 403, 429, 500)
] + [
    URLError("fake-sensitive-detail"),
    TimeoutError("fake-sensitive-detail"),
])
def test_first_page_errors_are_not_reported_as_a_missing_image(monkeypatch, capsys, error):
    mock_responses(monkeypatch, {"token": REGISTRY_TOKEN}, error)

    assert hub.main([IMAGE]) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert IMAGE in output.err
    assert "등록된 이미지가 없습니다" not in output.err
    assert "fake-sensitive-detail" not in output.err


@pytest.mark.parametrize("image_name", [
    "",
    "ubuntu",
    "registry.example/team/backend",
    "localhost/backend",
    "https://hub.docker.com/team/backend",
    "team/backend:latest",
    "team/backend@sha256:abcdef",
    "team/backend/extra",
    "../backend",
    "team/..",
    "team/",
    "/backend",
])
def test_invalid_or_non_hub_references_fail_before_network(monkeypatch, image_name):
    requests = mock_responses(monkeypatch)

    with pytest.raises(hub.HubLookupError):
        hub.list_tags(image_name)

    assert not requests


@pytest.mark.parametrize("payload", [
    b"not JSON",
    [],
    {},
    {"token": ""},
    {"token": 12},
    {"access_token": ""},
])
def test_bad_auth_responses_stop_before_registry_access(monkeypatch, payload):
    requests = mock_responses(monkeypatch, payload)

    with pytest.raises(hub.HubLookupError):
        hub.list_tags(IMAGE)

    assert len(requests) == 1


@pytest.mark.parametrize("payload", [
    b"not JSON",
    [],
    {},
    {"name": IMAGE},
    {"name": IMAGE, "tags": {}},
    {"name": IMAGE, "tags": [None]},
    {"name": IMAGE, "tags": [{"name": "v1"}]},
    {"name": "another-user/another-repository", "tags": ["v1"]},
])
def test_bad_registry_responses_are_lookup_errors(monkeypatch, payload):
    mock_responses(monkeypatch, {"token": REGISTRY_TOKEN}, payload)

    with pytest.raises(hub.HubLookupError):
        hub.list_tags(IMAGE)


@pytest.mark.parametrize("tag", [
    "",
    "-invalid",
    "invalid/tag",
    "invalid:tag",
    "invalid\noutput",
    "a" * 129,
])
def test_invalid_tag_names_are_not_accepted(monkeypatch, tag):
    mock_responses(
        monkeypatch,
        {"token": REGISTRY_TOKEN},
        {"name": IMAGE, "tags": [tag]},
    )

    with pytest.raises(hub.HubLookupError):
        hub.list_tags(IMAGE)


@pytest.mark.parametrize("next_page", [
    SECOND_PAGE.replace("https://", "http://"),
    SECOND_PAGE.replace("registry-1.docker.io", "untrusted.example"),
    SECOND_PAGE.replace("registry-1.docker.io", "registry-1.docker.io@untrusted.example"),
    SECOND_PAGE.replace("/eagleindesert/", "/another-user/"),
    SECOND_PAGE.replace("/fix-my-home-be/", "/another-repository/"),
    SECOND_PAGE.replace("/tags/list", "/manifests/latest"),
    SECOND_PAGE + "#fragment",
    "https://[invalid",
])
def test_unsafe_pagination_never_receives_the_bearer_token(monkeypatch, next_page):
    requests = mock_responses(
        monkeypatch,
        {"token": REGISTRY_TOKEN},
        FakeResponse({"name": IMAGE, "tags": ["v1"]}, {"Link": f'<{next_page}>; rel="next"'}),
    )

    with pytest.raises(hub.HubLookupError):
        hub.list_tags(IMAGE)

    assert len(requests) == 2


@pytest.mark.parametrize("link", [
    "not-a-link",
    '<>; rel="next"',
    'https://registry-1.docker.io/not-enclosed; rel="next"',
])
def test_malformed_pagination_is_not_treated_as_a_complete_list(monkeypatch, link):
    requests = mock_responses(
        monkeypatch,
        {"token": REGISTRY_TOKEN},
        FakeResponse({"name": IMAGE, "tags": ["v-partial"]}, {"Link": link}),
    )

    with pytest.raises(hub.HubLookupError):
        hub.list_tags(IMAGE)

    assert len(requests) == 2


def test_repeated_page_url_cannot_loop_forever(monkeypatch):
    requests = mock_responses(
        monkeypatch,
        {"token": REGISTRY_TOKEN},
        FakeResponse({"name": IMAGE, "tags": ["v1"]}, {"Link": f'<{SECOND_PAGE}>; rel="next"'}),
        FakeResponse({"name": IMAGE, "tags": ["v2"]}, {"Link": f'<{SECOND_PAGE}>; rel="next"'}),
    )

    with pytest.raises(hub.HubLookupError):
        hub.list_tags(IMAGE)

    assert len(requests) == 3


@pytest.mark.parametrize("status", [401, 403, 404, 429])
@pytest.mark.parametrize("failure_at", ["auth", "second_page"])
def test_http_failures_report_target_without_tags_credentials_or_response_details(
    monkeypatch, capsys, status, failure_at,
):
    password = "fake-sensitive-docker-password"
    detail = "fake-sensitive-upstream-detail"
    use_credentials(monkeypatch, username="fake-docker-user", password=password)
    error_url = f"{AUTH_ORIGIN}/token" if failure_at == "auth" else SECOND_PAGE
    error = HTTPError(error_url, status, detail, {"Retry-After": "17"}, io.BytesIO(detail.encode()))
    responses = [error] if failure_at == "auth" else [
        {"token": REGISTRY_TOKEN},
        FakeResponse(
            {"name": IMAGE, "tags": ["v-partial"]},
            {"Link": f'<{SECOND_PAGE}>; rel="next"'},
        ),
        error,
    ]
    requests = mock_responses(monkeypatch, *responses)

    assert hub.main([IMAGE]) == 1

    output = capsys.readouterr()
    combined = output.out + output.err
    assert output.err
    assert IMAGE in combined
    assert "v-partial" not in combined
    assert password not in combined
    assert detail not in combined
    assert REGISTRY_TOKEN not in combined
    assert len(requests) == (1 if failure_at == "auth" else 3)


@pytest.mark.parametrize("error", [
    URLError("fake-sensitive-network-detail"),
    TimeoutError("fake-sensitive-network-detail"),
])
def test_network_failures_are_reported_without_internal_details(monkeypatch, capsys, error):
    mock_responses(monkeypatch, error)

    assert hub.main([IMAGE]) == 1

    output = capsys.readouterr()
    assert output.err
    assert IMAGE in output.out + output.err
    assert "fake-sensitive-network-detail" not in output.out + output.err


def test_main_ignores_removed_hub_token_and_prints_only_completed_tag_list(monkeypatch, capsys):
    old_hub_token = "fake-obsolete-hub-management-token"
    monkeypatch.setenv("DOCKER_HUB_ACCESS_TOKEN", old_hub_token)
    requests = mock_responses(
        monkeypatch,
        {"token": REGISTRY_TOKEN},
        FakeResponse({"name": IMAGE, "tags": ["v1"]}, {"Link": f'<{SECOND_PAGE}>; rel="next"'}),
        {"name": IMAGE, "tags": ["v2"]},
    )

    assert hub.main([IMAGE]) == 0

    output = capsys.readouterr()
    assert not output.err
    assert IMAGE in output.out
    assert output.out.index("v1") < output.out.index("v2")
    assert REGISTRY_TOKEN not in output.out
    assert old_hub_token not in output.out
    assert requests[0].get_header("Authorization") is None
    for request in requests:
        assert old_hub_token not in request.full_url
        assert old_hub_token not in str(request.header_items())
        assert old_hub_token.encode() not in (request.data or b"")
