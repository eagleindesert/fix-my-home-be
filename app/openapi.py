"""문서에서 생성한 설명과 실제 전송 규칙을 Swagger UI에 제공한다."""

import json
import re

from app.contract_data import ENDPOINTS, ENUM_DESCRIPTIONS, ENUMS, SCHEMA_DESCRIPTIONS, SCHEMAS, TAGS
from app.contracts import type_schema
from app.errors import DomainError

API_DESCRIPTION = """요구사항 v1.7 · FE·BE 분업 v1.4 · API v1.1 기준입니다. 기본 경로는 `/v1`입니다.

### 인증과 실행 순서

1. 계정이 없다면 `POST /v1/auth/signup`으로 로그인 ID와 비밀번호를 등록합니다.
   별도 인증 없이 일반 사용자로 가입하며, 이미 사용 중인 ID는 `409 ACCOUNT_EXISTS`입니다.
2. 가입 또는 사전 발급한 계정으로 `POST /v1/auth/login`의 **Try it out**을 실행합니다.
   브라우저가 받은 HttpOnly 세션 쿠키를 이후 같은 출처의 요청에 자동으로 보냅니다.
3. `GET /v1/auth/me`로 현재 역할을 확인하고, 기사 기능은 `PATCH /v1/auth/role`로
   허용된 `TECHNICIAN` 역할로 전환한 뒤 호출합니다.

쿠키 값을 Authorize 창에 직접 입력하지 않습니다. Swagger UI와 API를 같은 호스트에서 열고,
상태 변경 요청의 출처는 `FMH_PUBLIC_ORIGIN`과 일치시킵니다. 운영 쿠키는 HTTPS에서 사용합니다.

### 요청과 응답

- 성공 JSON은 `data`로 감싸고 오류는 `ErrorResponseDTO`를 루트에 반환합니다.
  `204`는 본문이 없으며 이미지·PDF 응답은 파일 바이트입니다.
- 필요한 API에는 **큰따옴표를 포함한** `Idempotency-Key`를 입력합니다.
  같은 요청을 재전송할 때는 같은 키를, 내용·기대 버전이 바뀌면 새 키를 사용합니다.
- `expectedRevision`·`sourceRevision` 등은 최신 조회 응답의 값을 사용합니다.
  `409`가 발생하면 오류 사유와 현재 상태를 확인하고 필요한 자료를 다시 조회합니다.
- multipart의 `metadata`·`source`에는 DTO를 JSON 직렬화한 **문자열**을 입력합니다.
  `files`는 JPEG·PNG 파일을 반복 첨부하고, 메타정보의 개수·순서를 맞춥니다.
  요청 사진은 파일당 10,000,000 Byte, 업로드당 1~5장, 요청 전체 30장까지입니다.
- 날짜는 `YYYY-MM-DD`, 시각은 시간대를 포함한 ISO 8601입니다. 기준 시간대는 `Asia/Seoul`입니다.
- 페이지 목록은 `limit` 기본 20·범위 1~100입니다. 같은 경로·필터로 `nextCursor`를 전달하며,
  `nextCursor=null`이면 마지막 페이지입니다.
- AI·PDF·삭제 작업의 `202`는 접수 완료입니다. 해당 작업 조회의 `status`·`error`로 완료 여부를
  확인합니다. 조회 HTTP `200`만으로 작업 성공을 판단하지 않습니다. AI는 명시적으로 요청할 때만 실행합니다.

각 API를 펼치면 권한·선행 조건·처리 규칙, 파라미터, 요청 DTO와 상태 코드별 오류를 확인할 수 있습니다.
"""

SWAGGER_UI_PARAMETERS = {
    "filter": True,
    "docExpansion": "none",
    "displayRequestDuration": True,
    "defaultModelsExpandDepth": 0,
    "withCredentials": True,
    "validatorUrl": None,
}

IDEMPOTENCY_DESCRIPTION = (
    '큰따옴표를 포함한 ASCII 문자열입니다. 예: "request-001". '
    "같은 계정·메서드·실제 경로에서 같은 내용 재전송에는 같은 키를 사용합니다. "
    "내용·기대 버전 변경에는 새 키가 필요하며 같은 키로 바꾸면 409입니다. "
    "접수된 비동기 작업은 같은 키로 새 작업을 만들지 않습니다."
)

COMMON_ERRORS = {
    "400": ("BAD_REQUEST", "JSON 구문·중복 키·쿼리 또는 multipart 파트 형식이 올바르지 않습니다."),
    "401": ("AUTHENTICATION_REQUIRED", "세션이 없거나 만료되었습니다. 로그인 후 다시 요청하세요."),
    "403": ("ACCESS_DENIED", "활성 역할·소유자·관계 권한 또는 요청 출처가 허용되지 않습니다."),
    "404": ("RESOURCE_NOT_FOUND", "대상이 없거나 삭제되었습니다."),
    "409": ("VERSION_CONFLICT", "현재 버전·상태·근거 자료 또는 일정 조건을 다시 확인하세요."),
    "413": ("PAYLOAD_TOO_LARGE", "요청 본문 또는 파일 크기가 허용 범위를 초과했습니다."),
    "415": ("UNSUPPORTED_MEDIA_TYPE", "Content-Type 또는 실제 파일 형식이 지원되지 않습니다."),
    "422": ("VALIDATION_ERROR", "필수 필드·타입·범위·참조 조건을 확인하세요. fieldErrors에 상세 사유를 반환합니다."),
    "500": ("INTERNAL_ERROR", "내부 처리에 실패했습니다. retryable과 requiredActions를 확인하세요."),
    "503": ("SERVICE_UNAVAILABLE", "일시적으로 처리할 수 없습니다. retryable과 requiredActions를 확인하세요."),
}

REQUEST_EXAMPLES = {
    ("POST", "/auth/signup"): {"loginId": "new-user", "password": "example-password-123"},
    ("POST", "/auth/login"): {"loginId": "new-user", "password": "example-password-123"},
    ("PATCH", "/auth/role"): {"role": "TECHNICIAN"},
    ("POST", "/requests"): {
        "metadata": json.dumps({
            "symptom": "싱크대 수전에서 물이 샙니다.",
            "photos": [{"description": "수전 사진", "capturedOn": None, "dateConfirmed": False}],
        }, ensure_ascii=False),
    },
}


def documented_type(kind):
    if kind.endswith("?"):
        return {"anyOf": [documented_type(kind[:-1]), {"type": "null"}]}
    if kind.endswith("[]"):
        return {"type": "array", "items": documented_type(kind[:-2])}
    if kind.startswith("PageDTO<"):
        return {
            "type": "object", "required": ["items", "nextCursor"],
            "properties": {
                "items": {**documented_type(kind[8:-1] + "[]"), "description": "현재 조건에 맞는 결과. 결과가 없으면 빈 배열."},
                "nextCursor": {**documented_type("string?"), "description": "다음 페이지 커서. 마지막 페이지는 null."},
            },
        }
    if kind in ENUMS:
        return {"$ref": f"#/components/schemas/{kind}"}
    return type_schema(kind)


def documented_object(fields):
    return {
        "type": "object", "additionalProperties": False,
        "required": [field["name"] for field in fields if field["required"]],
        "properties": {
            field["name"]: {**documented_type(field["type"]), "description": field["description"]}
            for field in fields
        },
    }


def request_body(endpoint):
    content_type = "multipart/form-data" if endpoint["multipart"] else "application/json"
    schema = documented_object(endpoint["body"])
    example = REQUEST_EXAMPLES.get((endpoint["method"], endpoint["path"]))
    media = {"schema": schema}
    if endpoint["multipart"]:
        media["encoding"] = {}
        for field in endpoint["body"]:
            name = field["name"]
            if field["type"] in ("binary", "binary[]"):
                media["encoding"][name] = {"contentType": "image/jpeg, image/png"}
            else:
                media["encoding"][name] = {"contentType": "text/plain; charset=utf-8"}
                if example and name in example:
                    schema["properties"][name]["example"] = example[name]
    elif example:
        media["example"] = example
    if endpoint["path"] in ("/auth/signup", "/auth/login"):
        schema["properties"]["password"].update({"format": "password", "writeOnly": True})
    if endpoint["path"] == "/auth/signup":
        schema["properties"]["loginId"].update({"minLength": 1, "maxLength": 128})
        schema["properties"]["password"]["minLength"] = 12
    description = (
        "DTO를 JSON 문자열 Form 필드로 입력하고 파일을 첨부합니다."
        if endpoint["multipart"]
        else "정의된 필드만 JSON 객체로 전송합니다. 생략과 null은 구분합니다."
    )
    return {
        "required": True,
        "description": description,
        "content": {content_type: media},
    }


def success_response(endpoint, settings):
    response = {"description": endpoint["response_description"] or endpoint["summary"]}
    if endpoint["response"]:
        response["content"] = {"application/json": {"schema": {
            "type": "object", "required": ["data"],
            "properties": {"data": documented_type(endpoint["response"])},
        }}}
    elif endpoint["status"] != 204:
        media_types = ["application/pdf"] if endpoint["path"].startswith("/pdf-jobs") else ["image/jpeg", "image/png"]
        response["content"] = {
            media_type: {"schema": {"type": "string", "format": "binary"}} for media_type in media_types
        }
    if endpoint["response_headers"]:
        response["headers"] = {
            name: {"description": description, "schema": {"type": "string"}}
            for name, description in endpoint["response_headers"].items()
        }
        if "Set-Cookie" in response["headers"]:
            action = "만료" if endpoint["path"] == "/auth/logout" else "발급"
            secure = "; Secure" if settings.cookie_secure else ""
            response["headers"]["Set-Cookie"]["description"] = (
                f"{settings.session_cookie} 세션 쿠키 {action}. Path=/; HttpOnly; SameSite=Lax{secure}. "
                "토큰은 응답 JSON에 포함하지 않습니다."
            )
    return response


def error_responses(endpoint):
    statuses = {"500", "503", *endpoint["errors"]}
    if endpoint["authenticated"]:
        statuses.update(("401", "403"))
    if endpoint["path_parameters"]:
        statuses.add("404")
    if endpoint["query"] or endpoint["body"]:
        statuses.update(("400", "422"))
    if endpoint["method"] != "GET":
        statuses.add("403")
    if endpoint["body"]:
        statuses.update(("413", "415"))
    if endpoint["idempotent"]:
        statuses.update(("400", "409"))
    responses = {}
    for status in sorted(statuses):
        code, message = COMMON_ERRORS[status]
        reasons = endpoint["errors"].get(status, [])
        description = "\n".join(f"- {reason}" for reason in reasons) if reasons else message
        if status == "400" and endpoint["idempotent"]:
            description += "\n\n`INVALID_IDEMPOTENCY_KEY`: 필수 키 누락 또는 큰따옴표·ASCII 형식 오류."
        if status == "409" and endpoint["idempotent"]:
            description += "\n\n`IDEMPOTENCY_KEY_REUSED`: 같은 키로 다른 내용 전송. `IDEMPOTENCY_IN_PROGRESS`: 반영 여부 확인 중."
        codes = re.findall(r"`([A-Z][A-Z_]+)`", " ".join(reasons))
        example_code = codes[0] if codes else code
        responses[status] = {
            "description": description,
            "content": {"application/json": {
                "schema": documented_type("ErrorResponseDTO"),
                "example": DomainError(example_code, reasons[0] if reasons else message,
                                       int(status), retryable=status in ("500", "503")).body(),
            }},
        }
    return responses


def enrich_openapi(document, settings):
    schemas = document.setdefault("components", {}).setdefault("schemas", {})
    for name, fields in SCHEMAS.items():
        if name == "PageDTO<T>":
            continue
        schemas[name] = type_schema(name) if name == "BoundingBoxDTO" else documented_object(fields)
        schemas[name]["description"] = SCHEMA_DESCRIPTIONS.get(name) or f"{name} 필드 정의."
    schemas.update({
        name: {"type": "string", "enum": values, "description": ENUM_DESCRIPTIONS[name]}
        for name, values in ENUMS.items()
    })
    document["tags"] = TAGS
    document["components"]["securitySchemes"] = {"session": {
        "type": "apiKey", "in": "cookie", "name": settings.session_cookie,
        "description": "같은 출처에서 로그인하면 브라우저가 세션 쿠키를 자동 전송합니다. Authorize에 직접 입력하지 않습니다.",
    }}
    for endpoint in ENDPOINTS:
        operation = document["paths"]["/v1" + endpoint["path"]][endpoint["method"].lower()]
        operation["tags"] = [endpoint["tag"]]
        operation["description"] = endpoint["description"]
        operation["security"] = [{"session": []}] if endpoint["authenticated"] else []
        operation["parameters"] = [
            {"name": field["name"], "in": "path", "required": True,
             "description": field["description"], "schema": documented_type(field["type"])}
            for field in endpoint["path_parameters"]
        ]
        for field in endpoint["query"]:
            schema = documented_type(field["type"])
            if field["name"] == "limit":
                schema.update({"default": 20, "minimum": 1, "maximum": 100})
            operation["parameters"].append({
                "name": field["name"], "in": "query", "required": field["required"],
                "description": field["description"], "schema": schema,
            })
        if endpoint["idempotent"]:
            operation["parameters"].append({
                "name": "Idempotency-Key", "in": "header", "required": True,
                "description": IDEMPOTENCY_DESCRIPTION, "example": '"request-001"',
                "schema": {"type": "string", "maxLength": 256, "pattern": '^"[\\x20-\\x21\\x23-\\x7e]+"$'},
            })
        if endpoint["body"]:
            operation["requestBody"] = request_body(endpoint)
        operation["responses"] = {
            str(endpoint["status"]): success_response(endpoint, settings),
            **error_responses(endpoint),
        }
    return document
