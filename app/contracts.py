"""문서 기반 전송 검증과 OpenAPI. 업무 조건은 서비스 계층에서 검사한다."""

import json
import math
from datetime import date

from app.contract_data import ENDPOINTS, ENUMS, SCHEMAS
from app.errors import DomainError, invalid
from app.time_rules import as_utc


def load_json(value):
    def unique(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("중복 JSON 키")
            result[key] = item
        return result
    try:
        return json.loads(value, object_pairs_hook=unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (ValueError, UnicodeError):
        raise DomainError("BAD_REQUEST", "올바른 JSON이 필요합니다. 중복 객체 키는 허용하지 않습니다.", 400)


def validate_type(value, kind, path, output=False):
    if kind == "BoundingBoxDTO":
        if not isinstance(value, list) or len(value) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in value):
            invalid("정규화된 좌표 네 개가 필요합니다.", path)
        if not (0 <= value[0] < value[2] <= 1 and 0 <= value[1] < value[3] <= 1):
            invalid("영역 좌표 범위가 올바르지 않습니다.", path)
        return value
    if kind == "ResourceStatus":
        return validate_type(value, "string", path, output)
    if kind.endswith("?"):
        return None if value is None else validate_type(value, kind[:-1], path, output)
    if kind.endswith("[]"):
        if not isinstance(value, list):
            invalid("배열이 필요합니다.", path)
        return [validate_type(item, kind[:-2], f"{path}.{i}", output) for i, item in enumerate(value)]
    if kind.startswith("PageDTO<"):
        if not isinstance(value, dict) or set(value) != {"items", "nextCursor"}:
            invalid("페이지 객체가 필요합니다.", path)
        validate_type(value["items"], kind[8:-1]+"[]", path+".items", output)
        validate_type(value["nextCursor"], "string?", path+".nextCursor", output)
        return value
    if kind in ENUMS:
        if value not in ENUMS[kind]:
            invalid(f"{kind} 값이 올바르지 않습니다.", path)
    elif kind in SCHEMAS:
        validate_object(value, SCHEMAS[kind], path, output)
        if not output and kind == "SourceDTO" and "verified" in value:
            invalid("verified는 서버 검증 필드입니다.", path + ".verified")
    elif kind == "boolean":
        if type(value) is not bool:
            invalid("불리언이 필요합니다.", path)
    elif kind in ("integer", "number"):
        if type(value) not in (int, float) or not math.isfinite(value) or (kind == "integer" and type(value) is not int):
            invalid("유효한 숫자가 필요합니다.", path)
    elif kind in ("string", "date", "dateTime"):
        if not isinstance(value, str) or not value.strip():
            invalid("비어 있지 않은 문자열이 필요합니다.", path)
        if len(value) > 100_000:
            invalid("문자열이 너무 깁니다.", path)
        if kind == "dateTime":
            as_utc(value)
        if kind == "date":
            try:
                date.fromisoformat(value)
            except ValueError:
                invalid("날짜는 YYYY-MM-DD 형식이어야 합니다.", path)
    elif kind.startswith('"'):
        if value != kind.strip('"'):
            invalid("고정 값이 올바르지 않습니다.", path)
    return value


def validate_object(value, fields, path="", output=False):
    if not isinstance(value, dict):
        invalid("객체가 필요합니다.", path)
    known = {f["name"] for f in fields}
    if not output and set(value) - known:
        invalid("정의되지 않은 입력 필드입니다.", next(iter(set(value) - known)))
    for field in fields:
        key = field["name"]
        location = f"{path}.{key}".strip(".")
        if key not in value:
            if field["required"] or output:
                invalid("필수 필드가 누락되었습니다.", location)
        else:
            validate_type(value[key], field["type"], location, output)


def type_schema(kind):
    if kind == "BoundingBoxDTO":
        return {"type": "array", "minItems": 4, "maxItems": 4, "items": {"type": "number", "minimum": 0, "maximum": 1}}
    if kind == "ResourceStatus":
        return {"type": "string"}
    if kind.endswith("?"):
        return {"anyOf": [type_schema(kind[:-1]), {"type": "null"}]}
    if kind.endswith("[]"):
        return {"type": "array", "items": type_schema(kind[:-2])}
    if kind.startswith("PageDTO<"):
        return {"type": "object", "required": ["items", "nextCursor"], "properties": {
            "items": {"type": "array", "items": type_schema(kind[8:-1])},
            "nextCursor": type_schema("string?")}}
    if kind in ENUMS:
        return {"type": "string", "enum": ENUMS[kind]}
    if kind in SCHEMAS or kind == "ErrorResponseDTO":
        return {"$ref": f"#/components/schemas/{kind}"}
    if kind in ("date", "dateTime", "binary"):
        return {"type": "string", "format": {"date": "date", "dateTime": "date-time", "binary": "binary"}[kind]}
    if kind.startswith('"'):
        return {"type": "string", "const": kind.strip('"')}
    return {"type": kind} if kind in ("string", "integer", "number", "boolean") else {}


def object_schema(fields, response=False):
    return {"type": "object", "additionalProperties": False,
            "required": [f["name"] for f in fields if response or f["required"]],
            "properties": {f["name"]: {**type_schema(f["type"]), "description": f["description"]} for f in fields}}


def project_output(value, kind):
    """DTO에 정의한 필드만 출력하고 선택 nullable 필드는 명시적으로 null로 보낸다."""
    if kind.endswith("?"):
        return None if value is None else project_output(value, kind[:-1])
    if kind.endswith("[]"):
        return [project_output(v, kind[:-2]) for v in value]
    if kind.startswith("PageDTO<"):
        return {"items": project_output(value["items"], kind[8:-1]+"[]"), "nextCursor": value["nextCursor"]}
    if kind in SCHEMAS and kind != "BoundingBoxDTO":
        result = {}
        for field in SCHEMAS[kind]:
            name, child = field["name"], field["type"]
            if name in value:
                result[name] = project_output(value[name], child)
            elif child.endswith("?"):
                result[name] = None
            elif child.endswith("[]"):
                result[name] = []
            else:
                raise RuntimeError(f"Missing response field: {kind}.{name}")
        return result
    return value


def enrich_openapi(document):
    schemas = document.setdefault("components", {}).setdefault("schemas", {})
    schemas.update({name: object_schema(fields) for name, fields in SCHEMAS.items() if name != "PageDTO<T>"})
    schemas["ErrorResponseDTO"] = {"type": "object", "properties": {
        "code": {"type": "string"}, "message": {"type": "string"},
        "retryable": {"type": "boolean"}, "permissionDenied": {"type": "boolean"},
        "currentState": {"anyOf": [type_schema("ResourceStateDTO"), {"type": "null"}]},
        "fieldErrors": type_schema("FieldErrorDTO[]"), "checks": type_schema("ScheduleCheckDTO[]"),
        "requiredActions": type_schema("string[]")}}
    document["components"]["securitySchemes"] = {"session": {"type": "apiKey", "in": "cookie", "name": "fmh_session"}}
    for endpoint in ENDPOINTS:
        operation = document["paths"]["/api/v1" + endpoint["path"]][endpoint["method"].lower()]
        operation["parameters"] = [{"name": name, "in": "path", "required": True, "schema": {"type": "string"}}
                                   for name in __import__("re").findall(r"\{(\w+)\}", endpoint["path"])]
        operation["parameters"] += [{"name": f["name"], "in": "query", "required": f["required"],
                                     "schema": type_schema(f["type"])} for f in endpoint["query"]]
        if endpoint["idempotent"]:
            operation["parameters"].append({"name": "Idempotency-Key", "in": "header", "required": True,
                                             "schema": {"type": "string", "pattern": '^"[\\x20-\\x21\\x23-\\x7e]+"$'}})
        if endpoint["body"]:
            content = "multipart/form-data" if endpoint["multipart"] else "application/json"
            operation["requestBody"] = {"required": True, "content": {content: {"schema": object_schema(endpoint["body"])}}}
        if endpoint["authenticated"]:
            operation["security"] = [{"session": []}]
        if endpoint["response"]:
            operation["responses"][str(endpoint["status"])] = {"description": "성공", "content": {
                "application/json": {"schema": {"type": "object", "required": ["data"],
                                                "properties": {"data": type_schema(endpoint["response"])}}}}}
        elif endpoint["method"] == "GET" and endpoint["path"] in ("/media/{mediaId}", "/pdf-jobs/{jobId}/content"):
            types = ["application/pdf"] if endpoint["path"].startswith("/pdf-jobs") else ["image/jpeg", "image/png"]
            operation["responses"]["200"] = {"description": "권한이 확인된 파일", "content": {
                content_type: {"schema": {"type": "string", "format": "binary"}} for content_type in types}}
        for status in (400, 401, 403, 404, 409, 413, 415, 422, 500, 503):
            operation["responses"][str(status)] = {"description": "공통 오류", "content": {
                "application/json": {"schema": type_schema("ErrorResponseDTO")}}}
    return document
