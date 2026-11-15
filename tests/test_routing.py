"""업무별 라우터의 경로 연결과 데코레이터 문서 설정을 검증한다."""

import importlib
import re

from fastapi.routing import APIRoute
from starlette.responses import JSONResponse

from app.contract_data import ENDPOINTS
from conftest import login


def test_every_endpoint_reaches_its_own_handler(client, environment, monkeypatch):
    application = environment[2]
    routes = [
        route for route in application.routes
        if isinstance(route, APIRoute) and route.path.startswith("/v1/")
    ]
    expected = {(endpoint["method"], "/v1" + endpoint["path"]) for endpoint in ENDPOINTS}
    actual = {(method, route.path) for route in routes for method in route.methods}
    assert actual == expected
    assert len(routes) == len(expected)
    assert len({route.endpoint for route in routes}) == len(expected)

    async def capture_operation(request, action):
        handler_name = action.__qualname__.split(".<locals>.")[0]
        return JSONResponse({
            "handler": f"{action.__module__}.{handler_name}",
            "pathParams": request.path_params,
        })

    for module_name in {route.endpoint.__module__ for route in routes}:
        module = importlib.import_module(module_name)
        monkeypatch.setattr(module, "run_endpoint", capture_operation)

    # 실제 HTTP 라우팅을 거쳐 정적 경로와 동적 경로의 우선순위까지 확인한다.
    for route in routes:
        params = {name: f"sample-{name}" for name in re.findall(r"\{(\w+)\}", route.path)}
        path = route.path.format(**params)
        for method in route.methods:
            response = client.request(method, path)
            assert response.status_code == 200, (method, path, response.text)
            assert response.json() == {
                "handler": f"{route.endpoint.__module__}.{route.endpoint.__qualname__}",
                "pathParams": params,
            }


def test_route_documentation_and_status_are_not_overwritten(client, environment, monkeypatch):
    application = environment[2]
    route = next(
        route for route in application.routes
        if isinstance(route, APIRoute) and route.path == "/v1/auth/me"
    )
    monkeypatch.setattr(route, "summary", "라우터에서 수정한 요약")
    monkeypatch.setattr(route, "description", "라우터에서 수정한 상세 설명")
    monkeypatch.setattr(route, "tags", ["EditedAuthentication"])
    monkeypatch.setattr(route, "status_code", 202)
    application.openapi_schema = None

    operation = client.get("/openapi.json").json()["paths"]["/v1/auth/me"]["get"]
    assert operation["summary"] == route.summary
    assert operation["description"] == route.description
    assert operation["tags"] == route.tags
    assert "202" in operation["responses"] and "200" not in operation["responses"]

    login(client)
    assert client.get("/v1/auth/me").status_code == 202


def test_authentication_precedes_request_parsing(client):
    response = client.patch(
        "/v1/requests/missing-request",
        content="{invalid-json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 401

    login(client)
    response = client.patch(
        "/v1/requests/missing-request",
        content="{invalid-json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "BAD_REQUEST"
