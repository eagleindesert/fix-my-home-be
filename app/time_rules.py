"""서울 시간, 계획 시간과 실제 시간, 이동 시간을 분리한 공통 규칙."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.errors import invalid, require

SEOUL = ZoneInfo("Asia/Seoul")


def as_utc(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            invalid("시간대가 포함된 ISO 8601 시각이 필요합니다.")
        if value.tzinfo is None:
            invalid("시각에는 시간대가 필요합니다.")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def iso(value):
    return as_utc(value).isoformat()


def quarter(value):
    value = as_utc(value)
    if value.astimezone(SEOUL).minute % 15 or value.second or value.microsecond:
        invalid("계획 시각은 15분 단위여야 합니다.")
    return value


def interval(value, planned=True):
    parse = quarter if planned else as_utc
    start, end = parse(value["startAt"]), parse(value["endAt"])
    require(start < end, "VALIDATION_ERROR", "종료는 시작 이후여야 합니다.", 422)
    return start, end


def overlap(a, b):
    return a[0] < b[1] and b[0] < a[1]


def lead_time(start, current):
    require(as_utc(start) - as_utc(current) >= timedelta(minutes=30),
            "INSUFFICIENT_LEAD_TIME", "확정 직전 최소 30분의 준비시간이 필요합니다.")


def fits_preference(start, end, preference):
    if not preference:
        return False
    if preference["mode"] == "FIXED":
        return as_utc(preference["fixedStartAt"]) == start
    return any(a <= start and end <= b for a, b in
               (interval(r) for r in preference.get("ranges", [])))
