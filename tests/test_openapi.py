import json
import re
from pathlib import Path

from fastapi.openapi.models import OpenAPI

from app.contract_data import ENDPOINTS
from app.contracts import validate_type
from conftest import login, picture, result
from scripts.generate_contract import render_contract

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
    page = client.get("/api/docs")
    assert page.status_code == 200 and "SwaggerUIBundle" in page.text
    assert "/api/openapi.json" in page.text
    assert '"withCredentials": true' in page.text
    schema = client.get("/api/openapi.json").json()
    OpenAPI.model_validate(schema)
    tags = {tag["name"] for tag in schema["tags"]}
    assert len(tags) == 12
    for endpoint in ENDPOINTS:
        operation = schema["paths"]["/api/v1" + endpoint["path"]][endpoint["method"].lower()]
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
    schema = client.get("/api/openapi.json").json()
    ai = schema["paths"]["/api/v1/requests/{requestId}/ai-jobs"]["post"]
    assert "종류별 대상·근거 버전" in ai["description"]
    assert "PHOTO_COMPARISON" in ai["description"] and "전송 금지" in ai["description"]
    assert "STALE_SOURCE" in ai["responses"]["409"]["description"]
    assert "QUESTION_LIMIT_REACHED" in ai["responses"]["409"]["description"]
    visit = schema["paths"]["/api/v1/requests/{requestId}/visit-details"]["put"]
    assert "재전송 응답" in visit["description"] and "VERSION_CONFLICT" in visit["description"]
    assert not any(parameter["name"] == "Idempotency-Key" for parameter in visit["parameters"])
    models = schema["components"]["schemas"]
    assert models["BoundingBoxDTO"]["type"] == "array"
    assert "수도·배관" in models["ServiceField"]["description"]
    assert models["ErrorResponseDTO"]["properties"]["retryable"]["description"]
    limit = next(
        parameter for parameter in schema["paths"]["/api/v1/requests"]["get"]["parameters"]
        if parameter["name"] == "limit"
    )
    assert limit["schema"] == {"type": "integer", "default": 20, "minimum": 1, "maximum": 100}


def test_documented_cookie_upload_and_response_formats_match_api(client):
    schema = client.get("/api/openapi.json").json()
    cookie_name = schema["components"]["securitySchemes"]["session"]["name"]
    login(client)
    assert client.cookies.get(cookie_name)
    operation = schema["paths"]["/api/v1/requests"]["post"]
    multipart = operation["requestBody"]["content"]["multipart/form-data"]
    assert multipart["schema"]["properties"]["files"]["items"]["format"] == "binary"
    assert multipart["schema"]["properties"]["metadata"]["type"] == "string"
    assert multipart["encoding"]["metadata"]["contentType"].startswith("text/plain")
    metadata = multipart["schema"]["properties"]["metadata"]["example"]
    validate_type(json.loads(metadata), "RequestInputDTO", "metadata")
    key = next(parameter["example"] for parameter in operation["parameters"] if parameter["name"] == "Idempotency-Key")
    root = result(client.post("/api/v1/requests", headers={"Idempotency-Key": key},
                              data={"metadata": metadata}, files=[("files", ("sink.png", picture(), "image/png"))]),
                  "RequestDTO", status=201)
    media_id = root["photos"]["unknownDatePhotos"][0]["media"]["mediaId"]
    media = client.get(f"/api/v1/media/{media_id}")
    documented_types = schema["paths"]["/api/v1/media/{mediaId}"]["get"]["responses"]["200"]["content"]
    assert media.headers["content-type"] in documented_types
    pdf_response = schema["paths"]["/api/v1/pdf-jobs/{jobId}/content"]["get"]["responses"]["200"]
    assert "application/pdf" in pdf_response["content"]
    assert "content" not in schema["paths"]["/api/v1/auth/logout"]["post"]["responses"]["204"]
    assert client.post("/api/v1/auth/logout").content == b""
    error = client.get("/api/v1/auth/me")
    assert error.status_code == 401
    validate_type(error.json(), "ErrorResponseDTO", "error", output=True)


def test_documentation_generation_matches_checked_in_contract():
    source = (ROOT / "docs/API명세서.md").read_text(encoding="utf-8")
    assert render_contract(source) == (ROOT / "app/contract_data.py").read_text(encoding="utf-8")
