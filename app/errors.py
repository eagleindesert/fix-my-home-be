"""API 명세의 공통 오류 응답."""

from dataclasses import dataclass, field


@dataclass
class DomainError(Exception):
    code: str
    message: str
    status: int = 409
    fields: list[dict] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    retryable: bool = False
    current_state: dict | None = None

    def body(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "fieldErrors": self.fields,
            "retryable": self.retryable,
            "permissionDenied": self.status in (401, 403),
            "currentState": self.current_state,
            "checks": self.checks,
            "requiredActions": self.actions,
        }


def require(condition, code, message, status=409, **kwargs):
    if not condition:
        raise DomainError(code, message, status, **kwargs)


def invalid(message, field_name=None):
    fields = [{"field": field_name, "code": "VALIDATION_ERROR", "message": message, "fileIndex": None}] if field_name else []
    raise DomainError("VALIDATION_ERROR", message, 422, fields=fields)
