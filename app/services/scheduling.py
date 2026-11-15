"""계획·실제 작업과 이동을 함께 검사하는 결정적 일정 엔진."""

import copy
from datetime import timedelta

from app.db import now
from app.errors import DomainError, require
from app.services import reference
from app.services.context import ACTIVE_RESERVATIONS
from app.time_rules import SEOUL, as_utc, fits_preference, interval, iso, overlap


def schedule_resource(ctx, technician):
    rows = ctx.find("SCHEDULE", technician_id=technician.id)
    return rows[0] if rows else None


def schedule_data(ctx, technician):
    row = schedule_resource(ctx, technician)
    return copy.deepcopy(row.data) if row else {"availability": [], "externalVisits": [],
                                              "departureLocationId": None, "returnLocationId": None}


def travel_minutes(ctx, start, end):
    require(start and end, "REFERENCE_DATA_MISSING", "출발·도착 대표 위치를 확인해야 합니다.")
    for row in ctx.references("TRAVEL"):
        if row.data["fromLocationId"] == start and row.data["toLocationId"] == end:
            return row.data["minutes"]
    raise DomainError("REFERENCE_DATA_MISSING", "해당 구간의 고정 이동시간표가 없습니다.")


def reservation_range(row):
    terms = row.data["agreement"]["terms"]
    start = row.data.get("actualStartedAt") or terms["startAt"]
    end = row.data.get("actualEndedAt") or row.data["currentExpectedEndAt"]
    return as_utc(start), as_utc(end)


def effective_location(ctx, row):
    if row.status in ("COMPLETED", "STOPPED"):
        return (row.data.get("performance") or {}).get("endLocationId")
    location = reference.region(ctx, row.data["agreement"]["terms"]["region"])
    return location["representativeLocationId"] if location else None


def check_schedule(ctx, technician, start, end, region_value, preference=None,
                   exclude=None, operation="CREATE", proposed_schedule=None):
    require(start < end, "SCHEDULE_RECHECK_REQUIRED", "예상 종료 시각을 다시 확인해야 합니다.")
    if preference:
        require(fits_preference(start, end, preference), "TECHNICIAN_CONFLICT", "작업 전체가 사용자 방문 조건에 포함되어야 합니다.")
    schedule = proposed_schedule or schedule_data(ctx, technician)
    windows = [interval(r) for r in schedule["availability"]]
    window = next((r for r in windows if r[0] <= start and end <= r[1]), None)
    require(window, "TECHNICIAN_CONFLICT", "기사의 방문 가능 구간을 벗어납니다.")
    location = reference.region(ctx, region_value)
    require(location and location["representativeLocationId"], "REFERENCE_DATA_MISSING", "작업 동의 대표 위치가 필요합니다.")
    location_id = location["representativeLocationId"]
    occupied = []
    current = now()
    for row in ctx.find("RESERVATION", technician_id=technician.id):
        if row.id == exclude:
            continue
        span = reservation_range(row)
        if row.status in ("IN_PROGRESS", "STOP_REQUESTED"):
            require(operation != "START_WORK", "TECHNICIAN_CONFLICT", "같은 기사의 다른 작업이 진행 중입니다.")
            require(span[1] > current, "SCHEDULE_RECHECK_REQUIRED", "초과 작업의 종료 예상을 갱신해야 합니다.")
        if row.status in ACTIVE_RESERVATIONS:
            occupied.append((span, effective_location(ctx, row), row.id))
        elif row.status in ("COMPLETED", "STOPPED") and span[1] <= start and span[1].astimezone(SEOUL).date() == start.astimezone(SEOUL).date():
            occupied.append(((span[1], span[1]), effective_location(ctx, row), row.id))
    for visit in schedule["externalVisits"]:
        occupied.append((interval(visit["range"]), visit["locationId"], visit["externalVisitId"]))
    for span, _, _ in occupied:
        require(not overlap((start, end), span), "TECHNICIAN_CONFLICT", "기사의 작업 시간이 충돌합니다.")
    before = sorted([r for r in occupied if r[0][1] <= start], key=lambda r: r[0][1])
    after = sorted([r for r in occupied if r[0][0] >= end], key=lambda r: r[0][0])
    prev = before[-1] if before and before[-1][0][1] >= window[0] else None
    following = after[0] if after and after[0][0][0] <= window[1] else None
    before_time = prev[0][1] if prev else window[0]
    before_location = prev[1] if prev else schedule.get("departureLocationId")
    after_time = following[0][0] if following else window[1]
    after_location = following[1] if following else schedule.get("returnLocationId")
    first = travel_minutes(ctx, before_location, location_id)
    second = travel_minutes(ctx, location_id, after_location)
    require(before_time + timedelta(minutes=first) <= start and end + timedelta(minutes=second) <= after_time,
            "TECHNICIAN_CONFLICT", "앞뒤 작업과 이동시간이 충돌합니다.")
    try:
        original = travel_minutes(ctx, before_location, after_location)
    except DomainError:
        original = None
    route = None if original is None else {
        "insertionRange": {"startAt": iso(start), "endAt": iso(end)},
        "beforeLocationId": before_location, "requestLocationId": location_id,
        "afterLocationId": after_location, "beforeToRequestMinutes": first,
        "requestToAfterMinutes": second, "beforeToAfterMinutes": original,
        "additionalMinutes": first + second - original, "referenceVersions": reference.versions(ctx)}
    return route


def visit_overlaps(ctx, root_id, item_id, technician_id, start, end, exclude=None):
    values = []
    for row in ctx.find("RESERVATION", request_id=root_id):
        if row.id == exclude or row.item_id == item_id or row.technician_id == technician_id or row.status not in ACTIVE_RESERVATIONS:
            continue
        span = reservation_range(row)
        if overlap((start, end), span):
            values.append({"reservationId": row.id, "workItemId": row.item_id, "technicianId": row.technician_id,
                           "agreementVersion": row.data["agreement"]["agreementVersion"],
                           "range": {"startAt": iso(max(start, span[0])), "endAt": iso(min(end, span[1]))}})
    return sorted(values, key=lambda value: value["reservationId"])


def candidate_slots(preference, duration):
    if preference["mode"] == "FIXED":
        start = as_utc(preference["fixedStartAt"])
        yield start, start + timedelta(minutes=duration)
        return
    for window in preference["ranges"]:
        start, end = interval(window)
        # Visit inputs are capped to 31 days by validation at the API boundary.
        require(end-start <= timedelta(days=31), "VALIDATION_ERROR", "방문 구간은 31일 이내로 입력하세요.", 422)
        while start + timedelta(minutes=duration) <= end:
            yield start, start + timedelta(minutes=duration)
            start += timedelta(minutes=15)


def candidate_fit(ctx, item, technician, day=None):
    estimate = reference.duration(ctx, item)
    preference = item.data["facts"].get("visitPreference")
    if not preference or estimate["minutes"] is None:
        return "UNKNOWN", None, "추천 소요 시간 또는 방문 조건이 미확인입니다."
    root = ctx.get(item.request_id, "REQUEST")
    routes, matched, last_error = [], False, None
    for start, end in candidate_slots(preference, estimate["minutes"]):
        if day and start.astimezone(SEOUL).date().isoformat() != day:
            continue
        if start < now() + timedelta(minutes=30):
            continue
        try:
            route = check_schedule(ctx, technician, start, end, root.data["region"], preference)
            matched = True
            if route:
                routes.append(route)
        except DomainError as error:
            last_error = error
    if matched:
        return "MATCHED", min(routes, key=lambda r: (r["additionalMinutes"], r["insertionRange"]["startAt"])) if routes else None, None
    unknown = last_error and last_error.code in ("REFERENCE_DATA_MISSING", "SCHEDULE_RECHECK_REQUIRED")
    return "UNKNOWN" if unknown else "NOT_MATCHED", None, last_error.message if last_error else "삽입 가능한 일정이 없습니다."
