"""공개 회원가입의 입력·중복·세션 경계와 동시 가입을 검증한다."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import func, select

from app.db import Account, LoginSession, Resource
from app.security import verify_password
from conftest import APIClient, login, result


SIGNUP_PATH = "/v1/auth/signup"
PASSWORD = "signup-password-123"


def test_signup_creates_user_without_session_and_can_log_in(client, environment):
    settings, factory, _ = environment
    credentials = {"loginId": "new-member", "password": PASSWORD}
    response = client.post(SIGNUP_PATH, json=credentials)
    account = result(response, "SignupDTO", 201)
    assert account == {
        "accountId": account["accountId"],
        "loginId": "new-member",
        "availableRoles": ["USER"],
    }
    assert account["accountId"]
    assert "set-cookie" not in response.headers
    assert settings.session_cookie not in client.cookies
    assert client.get("/v1/auth/me").status_code == 401

    with factory() as db:
        stored = db.get(Account, account["accountId"])
        assert stored.password_hash != PASSWORD
        assert verify_password(PASSWORD, stored.password_hash)
        assert stored.roles == ["USER"]
        assert db.scalar(select(func.count()).select_from(LoginSession)) == 0
        assert db.scalar(select(Resource).where(
            Resource.kind == "TECHNICIAN", Resource.owner_id == stored.id,
        )) is None

    session = result(client.post("/v1/auth/login", json=credentials), "SessionDTO")
    assert session["accountId"] == account["accountId"]
    assert session["activeRole"] == "USER"
    assert session["availableRoles"] == ["USER"]
    assert session["technicianId"] is None
    assert result(client.get("/v1/auth/me"), "SessionDTO") == session
    denied = client.patch("/v1/auth/role", json={"role": "TECHNICIAN"})
    assert denied.status_code == 403 and denied.json()["code"] == "ROLE_FORBIDDEN"


@pytest.mark.parametrize("existing_account", [False, True])
def test_duplicate_login_id_preserves_existing_account(client, environment, existing_account):
    login_id = "owner" if existing_account else "duplicate-member"
    original_password = "testing-password-123" if existing_account else PASSWORD
    if not existing_account:
        result(client.post(SIGNUP_PATH, json={
            "loginId": login_id, "password": original_password,
        }), "SignupDTO", 201)
    with environment[1]() as db:
        original = db.scalar(select(Account).where(Account.login_id == login_id))
        original_id, original_hash = original.id, original.password_hash

    rejected = client.post(SIGNUP_PATH, json={
        "loginId": login_id, "password": "replacement-password-456",
    })
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "ACCOUNT_EXISTS"
    assert not rejected.json()["retryable"]
    assert "set-cookie" not in rejected.headers
    with environment[1]() as db:
        accounts = db.scalars(select(Account).where(Account.login_id == login_id)).all()
        assert len(accounts) == 1
        assert accounts[0].id == original_id
        assert accounts[0].password_hash == original_hash
    session = result(client.post("/v1/auth/login", json={
        "loginId": login_id, "password": original_password,
    }), "SessionDTO")
    assert session["accountId"] == original_id
    assert client.post("/v1/auth/login", json={
        "loginId": login_id, "password": "replacement-password-456",
    }).status_code == 401


@pytest.mark.parametrize("body", [
    {"loginId": "", "password": PASSWORD},
    {"loginId": "   ", "password": PASSWORD},
    {"loginId": " padded", "password": PASSWORD},
    {"loginId": "padded ", "password": PASSWORD},
    {"loginId": "x" * 129, "password": PASSWORD},
    {"loginId": 123, "password": PASSWORD},
    {"password": PASSWORD},
    {"loginId": "invalid-member"},
    {"loginId": "invalid-member", "password": ""},
    {"loginId": "invalid-member", "password": "x" * 11},
    {"loginId": "invalid-member", "password": 123},
    {"loginId": "invalid-member", "password": PASSWORD, "roles": ["TECHNICIAN"]},
    {"loginId": "invalid-member", "password": PASSWORD, "role": "TECHNICIAN"},
])
def test_invalid_signup_does_not_create_account(client, environment, body):
    with environment[1]() as db:
        before = db.scalar(select(func.count()).select_from(Account))
    response = client.post(SIGNUP_PATH, json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    with environment[1]() as db:
        assert db.scalar(select(func.count()).select_from(Account)) == before


def test_signup_accepts_id_and_password_length_boundaries(client):
    credentials = {"loginId": "x" * 128, "password": "a" * 12}
    account = result(client.post(SIGNUP_PATH, json=credentials), "SignupDTO", 201)
    assert account["loginId"] == credentials["loginId"]
    assert result(client.post("/v1/auth/login", json=credentials))["accountId"] == account["accountId"]


def test_signup_respects_origin_boundary(client, environment):
    response = client.post(SIGNUP_PATH, headers={"Origin": "https://untrusted.example"},
                           json={"loginId": "origin-member", "password": PASSWORD})
    assert response.status_code == 403 and response.json()["code"] == "ORIGIN_FORBIDDEN"
    with environment[1]() as db:
        assert db.scalar(select(Account).where(Account.login_id == "origin-member")) is None


def test_signup_keeps_existing_authenticated_session(client, environment):
    original = login(client)
    token = client.cookies.get(environment[0].session_cookie)
    response = client.post(SIGNUP_PATH, json={"loginId": "another-member", "password": PASSWORD})
    created = result(response, "SignupDTO", 201)
    assert created["accountId"] != original["accountId"]
    assert "set-cookie" not in response.headers
    assert client.cookies.get(environment[0].session_cookie) == token
    assert result(client.get("/v1/auth/me"), "SessionDTO") == original


def test_concurrent_signup_creates_exactly_one_account(environment):
    barrier = Barrier(2)
    credentials = {"loginId": "concurrent-member", "password": PASSWORD}

    def signup(_):
        with APIClient(environment[2]) as client:
            barrier.wait(timeout=10)
            response = client.post(SIGNUP_PATH, json=credentials)
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(signup, range(2)))
    assert sorted(status for status, _ in responses) == [201, 409]
    assert next(body for status, body in responses if status == 409)["code"] == "ACCOUNT_EXISTS"
    created = next(body["data"] for status, body in responses if status == 201)
    with environment[1]() as db:
        accounts = db.scalars(select(Account).where(Account.login_id == credentials["loginId"])).all()
        assert len(accounts) == 1 and accounts[0].id == created["accountId"]
        assert verify_password(PASSWORD, accounts[0].password_hash)
