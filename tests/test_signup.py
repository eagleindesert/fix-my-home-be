"""공개 회원가입의 역할·세션·초기 기사 지역과 트랜잭션 계약."""

import pytest
from sqlalchemy import func, select

from app.db import Account, LoginSession, ReferenceData, Resource
from app.errors import DomainError
from app.security import token_hash, verify_password
from conftest import login, result


PASSWORD = "new-account-password-123"


def signup_body(**changes):
    return {"loginId": "new-user", "password": PASSWORD, "role": "USER", **changes}


def row_counts(factory):
    with factory() as db:
        return tuple(db.scalar(select(func.count()).select_from(model))
                     for model in (Account, Resource, LoginSession))


@pytest.mark.parametrize("role", ["USER", "TECHNICIAN"])
def test_signup_logs_in_and_persists_the_allowed_roles(client, environment, role):
    settings, factory, _ = environment
    response = client.post("/v1/auth/signup", json=signup_body(role=role))
    session = result(response, "SessionDTO", 201)
    expected_roles = ["USER", "TECHNICIAN"] if role == "TECHNICIAN" else ["USER"]
    assert session["activeRole"] == "USER"
    assert session["availableRoles"] == expected_roles
    assert bool(session["technicianId"]) == (role == "TECHNICIAN")
    assert result(client.get("/v1/auth/me"), "SessionDTO") == session
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    assert client.cookies.get(settings.session_cookie)
    assert "password" not in response.text and PASSWORD not in response.text

    with factory() as db:
        account = db.get(Account, session["accountId"])
        assert account.login_id == "new-user" and account.roles == expected_roles
        assert account.password_hash != PASSWORD and verify_password(PASSWORD, account.password_hash)
        assert not db.scalar(select(Resource).where(Resource.kind == "SCHEDULE", Resource.owner_id == account.id))

    switch = client.patch("/v1/auth/role", json={"role": "TECHNICIAN"})
    assert switch.status_code == (200 if role == "TECHNICIAN" else 403)
    assert client.post("/v1/auth/logout").status_code == 204
    signed_in = result(client.post("/v1/auth/login", json={"loginId": "new-user", "password": PASSWORD}), "SessionDTO")
    assert signed_in == session


def test_signup_rotates_existing_session_and_initializes_technician_region(client, environment):
    settings, factory, _ = environment
    previous = login(client)
    old_token = client.cookies.get(settings.session_cookie)
    session = result(client.post("/v1/auth/signup", json=signup_body(
        role="TECHNICIAN", regionId="region-test")), "SessionDTO", 201)
    assert session["accountId"] != previous["accountId"]
    assert client.cookies.get(settings.session_cookie) != old_token
    assert result(client.get("/v1/auth/me"), "SessionDTO") == session

    with factory() as db:
        assert db.get(LoginSession, token_hash(old_token)) is None
        tech = db.get(Resource, session["technicianId"])
        assert tech.owner_id == session["accountId"]
        assert tech.data["profile"]["regionIds"] == ["region-test"]
        schedule = db.scalar(select(Resource).where(
            Resource.kind == "SCHEDULE", Resource.technician_id == tech.id))
        assert schedule.owner_id == session["accountId"]
        assert schedule.data == {
            "availability": [], "externalVisits": [],
            "departureLocationId": "test-location", "returnLocationId": "test-location",
        }

    result(client.patch("/v1/auth/role", json={"role": "TECHNICIAN"}), "SessionDTO")
    schedule = result(client.get("/v1/technicians/me/schedule", params={
        "from": "2026-11-15", "to": "2026-11-15"}), "ScheduleDTO")
    assert schedule["departureLocationId"] == schedule["returnLocationId"] == "test-location"


def test_duplicate_signup_preserves_the_existing_session_and_data(client, environment):
    settings, factory, _ = environment
    before_session = login(client)
    before_cookie = client.cookies.get(settings.session_cookie)
    before_counts = row_counts(factory)
    response = client.post("/v1/auth/signup", json=signup_body(
        loginId="owner", role="TECHNICIAN", regionId="region-test"))
    assert response.status_code == 409
    assert response.json()["code"] == "ACCOUNT_EXISTS"
    assert "set-cookie" not in response.headers
    assert client.cookies.get(settings.session_cookie) == before_cookie
    assert result(client.get("/v1/auth/me"), "SessionDTO") == before_session
    assert row_counts(factory) == before_counts


@pytest.mark.parametrize("changes", [
    {"loginId": "ab"}, {"loginId": "x" * 129}, {"loginId": "contains space"},
    {"loginId": "한글아이디"}, {"loginId": "new-user\n"}, {"loginId": None},
    {"password": "x" * 11}, {"password": "x" * 129}, {"password": " " * 12},
    {"role": "ADMIN"}, {"roles": ["USER", "TECHNICIAN"]},
    {"regionId": "region-test"}, {"role": "TECHNICIAN", "regionId": None},
])
def test_invalid_signup_does_not_create_an_account(client, environment, changes):
    before = row_counts(environment[1])
    response = client.post("/v1/auth/signup", json=signup_body(**changes))
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert "set-cookie" not in response.headers
    assert row_counts(environment[1]) == before


@pytest.mark.parametrize("missing", ["loginId", "password", "role"])
def test_signup_requires_all_credentials_and_role(client, missing):
    body = signup_body()
    del body[missing]
    response = client.post("/v1/auth/signup", json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("login_id, password", [
    ("a_-", "x" * 12), ("A.9_" + "x" * 124, "x" * 128),
])
def test_signup_accepts_length_boundaries_and_supported_id_characters(client, login_id, password):
    result(client.post("/v1/auth/signup", json=signup_body(
        loginId=login_id, password=password)), "SessionDTO", 201)
    result(client.post("/v1/auth/login", json={"loginId": login_id, "password": password}), "SessionDTO")


@pytest.mark.parametrize("region_id", ["unknown-region", "unverified-region", "travel-test"])
def test_signup_rejects_unknown_unverified_or_wrong_kind_regions(client, environment, region_id):
    factory = environment[1]
    with factory() as db, db.begin():
        db.add(ReferenceData(id="unverified-region", kind="REGION", version="TEST-ONLY", verified=False,
                            data={"representativeLocationId": "test-location"}))
    before = row_counts(factory)
    response = client.post("/v1/auth/signup", json=signup_body(role="TECHNICIAN", regionId=region_id))
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_REFERENCE"
    assert row_counts(factory) == before


def test_failed_session_creation_rolls_back_signup_and_keeps_previous_login(client, environment, monkeypatch):
    settings, factory, _ = environment
    previous = login(client)
    previous_cookie = client.cookies.get(settings.session_cookie)
    before = row_counts(factory)

    def unavailable(*args, **kwargs):
        raise DomainError("SERVICE_UNAVAILABLE", "세션 발급 실패", 503)

    monkeypatch.setattr("app.api.new_session", unavailable)
    response = client.post("/v1/auth/signup", json=signup_body(role="TECHNICIAN", regionId="region-test"))
    assert response.status_code == 503
    assert row_counts(factory) == before
    assert client.cookies.get(settings.session_cookie) == previous_cookie
    assert result(client.get("/v1/auth/me"), "SessionDTO") == previous


def test_signup_rejects_cross_origin_requests(client, environment):
    before = row_counts(environment[1])
    response = client.post("/v1/auth/signup", headers={"Origin": "https://other.example"}, json=signup_body())
    assert response.status_code == 403
    assert row_counts(environment[1]) == before


def test_signup_openapi_documents_unauthenticated_input_cookie_and_errors(client):
    operation = client.get("/openapi.json").json()["paths"]["/v1/auth/signup"]["post"]
    assert operation["security"] == []
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert schema["required"] == ["loginId", "password", "role"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["loginId"]["maxLength"] == 128
    assert schema["properties"]["password"]["minLength"] == 12
    assert schema["properties"]["password"]["writeOnly"] is True
    assert "regionId" in schema["properties"]
    response = operation["responses"]["201"]
    assert response["content"]["application/json"]["schema"]["properties"]["data"]["$ref"].endswith("/SessionDTO")
    assert "HttpOnly" in response["headers"]["Set-Cookie"]["description"]
    assert "ACCOUNT_EXISTS" in operation["responses"]["409"]["description"]
