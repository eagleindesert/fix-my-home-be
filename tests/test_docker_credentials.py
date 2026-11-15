import base64
import json
import subprocess

import pytest

from scripts.etc import docker_credentials as credentials


HUB = "https://index.docker.io/v1/"
USERNAME = "fake-docker-user"
PASSWORD = "fake-password:with-colon"
TOKEN = "fake-device-identity-token"


@pytest.fixture(autouse=True)
def isolate_docker_credentials(tmp_path, monkeypatch):
    """A test can never fall through to a real config file or credential helper."""
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / "docker"))

    def unexpected_helper(*args, **kwargs):
        pytest.fail("A test must explicitly mock every credential-helper invocation.")

    monkeypatch.setattr(credentials.subprocess, "run", unexpected_helper)


def write_config(directory, content):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "config.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    return path


def inline_auth(username=USERNAME, password=PASSWORD):
    return base64.b64encode(f"{username}:{password}".encode()).decode()


def helper_response(monkeypatch, payload, *, returncode=0, stderr=""):
    calls = []

    def run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        stdout = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.CompletedProcess(arguments, returncode, stdout, stderr)

    monkeypatch.setattr(credentials.subprocess, "run", run)
    return calls


def test_missing_config_returns_none_without_creating_files(tmp_path):
    assert credentials.load_docker_credentials() is None
    assert not (tmp_path / "docker").exists()


def test_missing_hub_credentials_does_not_use_other_registry_login(tmp_path):
    write_config(tmp_path / "docker", {
        "auths": {"private.example": {"auth": inline_auth()}},
        "credHelpers": {"private.example": "unrelated"},
    })
    assert credentials.load_docker_credentials() is None


@pytest.mark.parametrize("server", credentials.HUB_SERVERS)
def test_inline_auth_supports_hub_aliases_and_password_colons(tmp_path, server, capsys):
    path = write_config(tmp_path / "docker", {"auths": {server: {"auth": inline_auth()}}})
    original = path.read_bytes()
    modified = path.stat().st_mtime_ns

    result = credentials.load_docker_credentials()

    assert result.username == USERNAME
    assert result.password == PASSWORD
    assert result.identity_token == ""
    assert USERNAME not in repr(result)
    assert PASSWORD not in repr(result)
    assert path.read_bytes() == original
    assert path.stat().st_mtime_ns == modified
    assert capsys.readouterr() == ("", "")


def test_identity_token_takes_priority_over_inline_auth(tmp_path):
    write_config(tmp_path / "docker", {"auths": {
        HUB: {"identitytoken": TOKEN, "auth": inline_auth()},
    }})

    result = credentials.load_docker_credentials()

    assert result.identity_token == TOKEN
    assert result.username == result.password == ""
    assert TOKEN not in repr(result)


def test_explicit_directory_overrides_docker_config(tmp_path):
    write_config(tmp_path / "docker", {"auths": {HUB: {"auth": inline_auth("ignored", "ignored")}}})
    requested = tmp_path / "requested"
    write_config(requested, {"auths": {HUB: {"auth": inline_auth()}}})

    assert credentials.load_docker_credentials(requested).username == USERNAME


def test_default_directory_uses_home_without_changing_home_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("DOCKER_CONFIG")
    fake_home = tmp_path / "fake-home"
    monkeypatch.setattr(credentials.Path, "home", classmethod(lambda cls: fake_home))
    write_config(fake_home / ".docker", {"auths": {HUB: {"auth": inline_auth()}}})

    assert credentials.load_docker_credentials().username == USERNAME


def test_cred_helpers_override_store_and_inline_credentials(tmp_path, monkeypatch):
    write_config(tmp_path / "docker", {
        "credHelpers": {HUB: "selected"},
        "credsStore": "not-selected",
        "auths": {HUB: {"auth": inline_auth("ignored", "ignored")}},
    })
    calls = helper_response(monkeypatch, {"Username": USERNAME, "Secret": PASSWORD})

    result = credentials.load_docker_credentials()

    assert result.username == USERNAME and result.password == PASSWORD
    arguments, options = calls[0]
    assert arguments == ["docker-credential-selected", "get"]
    assert options["input"] == HUB
    assert options["capture_output"] is True
    assert options["text"] is True and options["timeout"] == 15
    assert not options.get("shell")
    assert USERNAME not in str(arguments) and PASSWORD not in str(arguments)
    assert len(calls) == 1


def test_creds_store_uses_canonical_hub_server_and_device_token(tmp_path, monkeypatch):
    write_config(tmp_path / "docker", {
        "credsStore": "desktop",
        "auths": {HUB: {"auth": inline_auth()}},
    })
    calls = helper_response(monkeypatch, {"Username": "<token>", "Secret": TOKEN})

    result = credentials.load_docker_credentials()

    assert result.identity_token == TOKEN
    assert result.username == result.password == ""
    assert calls[0][0] == ["docker-credential-desktop", "get"]
    assert calls[0][1]["input"] == HUB
    assert TOKEN not in repr(result)


def test_alias_specific_helper_does_not_override_cli_hub_store(tmp_path, monkeypatch):
    write_config(tmp_path / "docker", {
        "credHelpers": {"docker.io": "not-selected"},
        "credsStore": "desktop",
    })
    calls = helper_response(monkeypatch, {"Username": USERNAME, "Secret": PASSWORD})

    assert credentials.load_docker_credentials().username == USERNAME
    assert calls[0][0] == ["docker-credential-desktop", "get"]
    assert calls[0][1]["input"] == HUB


def test_empty_hub_helper_bypasses_global_store_and_uses_file_auth(tmp_path):
    write_config(tmp_path / "docker", {
        "credHelpers": {HUB: ""},
        "credsStore": "not-selected",
        "auths": {HUB: {"auth": inline_auth()}},
    })

    assert credentials.load_docker_credentials().username == USERNAME


@pytest.mark.parametrize("missing_stream", ["stdout", "stderr"])
def test_helper_credentials_not_found_does_not_use_stale_inline_auth(
    tmp_path, monkeypatch, missing_stream,
):
    write_config(tmp_path / "docker", {
        "credsStore": "desktop", "auths": {HUB: {"auth": inline_auth()}},
    })
    message = "credentials not found in native keychain\n"
    helper_response(
        monkeypatch, message if missing_stream == "stdout" else "",
        returncode=1, stderr=message if missing_stream == "stderr" else "",
    )

    assert credentials.load_docker_credentials() is None


@pytest.mark.parametrize("content", [
    [],
    {"auths": []},
    {"credHelpers": []},
    {"credsStore": {"secret": PASSWORD}},
    {"credHelpers": {HUB: "../fake-sensitive-helper"}},
    {"auths": {HUB: PASSWORD}},
    {"auths": {HUB: {"identitytoken": {"secret": PASSWORD}}}},
    {"auths": {HUB: {"auth": "fake-sensitive-invalid-base64"}}},
    {"auths": {HUB: {"auth": base64.b64encode(b"fake-sensitive-no-colon").decode()}}},
    {"auths": {HUB: {"auth": base64.b64encode(b":fake-sensitive-password").decode()}}},
])
def test_invalid_config_is_sanitized_and_unchanged(tmp_path, capsys, content):
    path = write_config(tmp_path / "docker", content)
    original = path.read_bytes()

    with pytest.raises(credentials.DockerCredentialError) as error:
        credentials.load_docker_credentials()

    assert PASSWORD not in str(error.value)
    assert "fake-sensitive" not in str(error.value)
    assert path.read_bytes() == original
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("content", [
    b'{"private": "fake-sensitive-invalid-json"',
    b"\xfffake-sensitive-invalid-utf8",
])
def test_invalid_config_encoding_and_json_are_sanitized(tmp_path, content):
    directory = tmp_path / "docker"
    directory.mkdir()
    path = directory / "config.json"
    path.write_bytes(content)

    with pytest.raises(credentials.DockerCredentialError) as error:
        credentials.load_docker_credentials()

    assert "fake-sensitive" not in str(error.value)
    assert path.read_bytes() == content


@pytest.mark.parametrize("payload, returncode", [
    ("fake-sensitive-helper-output", 1),
    ("fake-sensitive-invalid-json", 0),
    (["fake-sensitive-value"], 0),
    ({"Username": USERNAME, "Secret": {"private": PASSWORD}}, 0),
    ({"Username": USERNAME, "Secret": ""}, 0),
])
def test_helper_errors_never_expose_output_or_credentials(
    tmp_path, monkeypatch, capsys, payload, returncode,
):
    write_config(tmp_path / "docker", {"credsStore": "desktop"})
    helper_response(monkeypatch, payload, returncode=returncode, stderr=PASSWORD)

    with pytest.raises(credentials.DockerCredentialError) as error:
        credentials.load_docker_credentials()

    for private in ("fake-sensitive", USERNAME, PASSWORD):
        assert private not in str(error.value)
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("error", [
    OSError("fake-sensitive-helper-error"),
    subprocess.TimeoutExpired(
        "fake-sensitive-helper-command", 15,
        output="fake-sensitive-helper-output", stderr=PASSWORD,
    ),
])
def test_helper_execution_failures_are_sanitized(tmp_path, monkeypatch, error):
    write_config(tmp_path / "docker", {"credsStore": "desktop"})

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(credentials.subprocess, "run", fail)
    with pytest.raises(credentials.DockerCredentialError) as caught:
        credentials.load_docker_credentials()
    assert "fake-sensitive" not in str(caught.value)
    assert PASSWORD not in str(caught.value)
