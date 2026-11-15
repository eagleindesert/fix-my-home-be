import json
import re
from pathlib import Path

import pytest
from fastapi.openapi.models import OpenAPI

from app.contract_data import ENDPOINTS
from app.contracts import validate_type
from app.main import create_app
from conftest import APIClient, login, picture, result
from scripts.etc.generate_contract import render_contract

ROOT = Path(__file__).resolve().parents[1]


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def test_swagger_ui_and_all_operations_have_usable_documentation(client):
    page = client.get("/docs")
    assert page.status_code == 200 and "SwaggerUIBundle" in page.text
    assert "/openapi.json" in page.text
    assert '"withCredentials": true' in page.text
    schema = client.get("/openapi.json").json()
    OpenAPI.model_validate(schema)
    tags = {tag["name"] for tag in schema["tags"]}
    assert len(tags) == 12
    for endpoint in ENDPOINTS:
        operation = schema["paths"]["/v1" + endpoint["path"]][endpoint["method"].lower()]
        assert operation["summary"] and "**설명**" in operation["description"]
        assert set(operation["tags"]) <= tags
        assert operation["security"] == ([{"session": []}] if endpoint["authenticated"] else [])
        paths = {parameter["name"] for parameter in operation["parameters"] if parameter["in"] == "path"}
        assert paths == set(re.findall(r"\{(\w+)\}", endpoint["path"]))
        assert all(parameter["description"] for parameter in operation["parameters"])
        for response in operation["responses"].values():
            assert response["description"] and response["description"] != "공통 오류"
    for node in walk(schema):
        if "$ref" in node:
            reference = schema
            for key in node["$ref"].removeprefix("#/").split("/"):
                reference = reference[key]


def test_policy_tables_models_and_errors_are_preserved(client):
    schema = client.get("/openapi.json").json()
    ai = schema["paths"]["/v1/requests/{requestId}/ai-jobs"]["post"]
    assert "종류별 대상·근거 버전" in ai["description"]
    assert "PHOTO_COMPARISON" in ai["description"] and "전송 금지" in ai["description"]
    assert "STALE_SOURCE" in ai["responses"]["409"]["description"]
    assert "QUESTION_LIMIT_REACHED" in ai["responses"]["409"]["description"]
    visit = schema["paths"]["/v1/requests/{requestId}/visit-details"]["put"]
    assert "재전송 응답" in visit["description"] and "VERSION_CONFLICT" in visit["description"]
    assert not any(parameter["name"] == "Idempotency-Key" for parameter in visit["parameters"])
    models = schema["components"]["schemas"]
    assert models["BoundingBoxDTO"]["type"] == "array"
    assert "수도·배관" in models["ServiceField"]["description"]
    assert models["ErrorResponseDTO"]["properties"]["retryable"]["description"]
    limit = next(
        parameter for parameter in schema["paths"]["/v1/requests"]["get"]["parameters"]
        if parameter["name"] == "limit"
    )
    assert limit["schema"] == {"type": "integer", "default": 20, "minimum": 1, "maximum": 100}


def test_documented_cookie_upload_and_response_formats_match_api(client):
    schema = client.get("/openapi.json").json()
    cookie_name = schema["components"]["securitySchemes"]["session"]["name"]
    login(client)
    assert client.cookies.get(cookie_name)
    operation = schema["paths"]["/v1/requests"]["post"]
    multipart = operation["requestBody"]["content"]["multipart/form-data"]
    assert multipart["schema"]["properties"]["files"]["items"]["format"] == "binary"
    assert multipart["schema"]["properties"]["metadata"]["type"] == "string"
    assert multipart["encoding"]["metadata"]["contentType"].startswith("text/plain")
    metadata = multipart["schema"]["properties"]["metadata"]["example"]
    validate_type(json.loads(metadata), "RequestInputDTO", "metadata")
    key = next(parameter["example"] for parameter in operation["parameters"] if parameter["name"] == "Idempotency-Key")
    root = result(client.post("/v1/requests", headers={"Idempotency-Key": key},
                              data={"metadata": metadata}, files=[("files", ("sink.png", picture(), "image/png"))]),
                  "RequestDTO", status=201)
    media_id = root["photos"]["unknownDatePhotos"][0]["media"]["mediaId"]
    media = client.get(f"/v1/media/{media_id}")
    documented_types = schema["paths"]["/v1/media/{mediaId}"]["get"]["responses"]["200"]["content"]
    assert media.headers["content-type"] in documented_types
    pdf_response = schema["paths"]["/v1/pdf-jobs/{jobId}/content"]["get"]["responses"]["200"]
    assert "application/pdf" in pdf_response["content"]
    assert "content" not in schema["paths"]["/v1/auth/logout"]["post"]["responses"]["204"]
    assert client.post("/v1/auth/logout").content == b""
    error = client.get("/v1/auth/me")
    assert error.status_code == 401
    validate_type(error.json(), "ErrorResponseDTO", "error", output=True)


def test_documentation_generation_matches_checked_in_contract():
    source = (ROOT / "docs/API명세서.md").read_text(encoding="utf-8")
    assert render_contract(source) == (ROOT / "app/contract_data.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("prefix, strip_prefix", [
    ("", False), ("/fixmyhome/api", False), ("/fixmyhome/api", True),
])
def test_swagger_schema_and_authenticated_requests_use_the_proxy_prefix(
    environment, prefix, strip_prefix,
):
    settings, factory, _ = environment
    settings = settings.model_copy(update={
        "root_path": prefix, "public_origin": "https://testserver", "cookie_secure": True,
    })
    application = create_app(settings, factory)

    # Schema generation can happen before the first HTTP request (e.g. exports).
    expected_servers = [{"url": prefix}] if prefix else []
    assert application.openapi().get("servers", []) == expected_servers

    async def proxy(scope, receive, send):
        if scope["type"] == "http" and strip_prefix:
            scope = dict(scope)
            scope["path"] = scope["path"].removeprefix(prefix)
            scope["raw_path"] = scope["path"].encode()
        await application(scope, receive, send)

    with APIClient(proxy, base_url="https://testserver") as client:
        noncanonical = client.get(f"{prefix}/docs/", follow_redirects=False)
        assert noncanonical.status_code == 404
        assert "location" not in noncanonical.headers
        page = client.get(f"{prefix}/docs")
        assert page.status_code == 200
        assert f"url: '{prefix}/openapi.json'" in page.text
        schema_response = client.get(f"{prefix}/openapi.json")
        assert schema_response.status_code == 200
        schema = schema_response.json()
        OpenAPI.model_validate(schema)
        assert schema.get("servers", []) == expected_servers
        assert all(path.startswith("/v1/") for path in schema["paths"])

        headers = {"Origin": "https://testserver"}
        authenticated = client.post(
            f"{prefix}/v1/auth/login", headers=headers,
            json={"loginId": "owner", "password": "testing-password-123"},
        )
        assert authenticated.status_code == 200
        assert client.cookies.get(settings.session_cookie)
        assert client.get(f"{prefix}/v1/auth/me").status_code == 200
        assert client.post(f"{prefix}/v1/auth/logout", headers=headers).status_code == 204
