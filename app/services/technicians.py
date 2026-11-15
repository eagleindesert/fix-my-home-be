"""기사 공개 정보, 준비된 사례, 일정 및 동선 후보."""

import copy
import hashlib
import hmac
from datetime import date, datetime, time, timedelta

from app.db import StoredFile, uid
from app.errors import DomainError, require
from app.media import normalize_image
from app.services import reference, reservations, scheduling, views
from app.services.context import ACTIVE_RESERVATIONS
from app.time_rules import SEOUL, as_utc, interval, iso, overlap


def owned_media(ctx, tech, ids):
    require(len(ids) == len(set(ids)), "INVALID_REFERENCE", "사진 ID가 중복되었습니다.", 422)
    for media_id in ids:
        file = ctx.db.get(StoredFile, media_id)
        require(file, "INVALID_REFERENCE", "사진을 찾을 수 없습니다.", 422)
        row = ctx.get(file.resource_id, "PORTFOLIO_PHOTO")
        require(row.technician_id == tech.id, "INVALID_REFERENCE", "본인 포트폴리오 사진만 사용할 수 있습니다.", 422)


def profile(ctx, tech, body):
    ctx.check_revision(tech, body["expectedRevision"])
    value = body["profile"]
    require(set(value["regionIds"]) <= {r.id for r in ctx.references("REGION")}, "INVALID_REFERENCE", "검증된 활동 지역을 선택하세요.", 422)
    require(value["fields"] and len(set(value["fields"])) == len(value["fields"]), "VALIDATION_ERROR", "전문 분야가 필요합니다.", 422)
    owned_media(ctx, tech, value["representativeMediaIds"])
    return ctx.save(tech, profile=value)


def upload(ctx, tech, files, source):
    for file in files:
        reference.verified_source(ctx, source, content=file["bytes"])
    source = reference.verified_source(ctx, source)
    require(1 <= len(files) <= 5, "UPLOAD_BATCH_REJECTED", "한 번에 1~5장을 업로드하세요.", 422)
    images = [normalize_image(f["bytes"]) for f in files]
    result = []
    for data, width, height, _ in images:
        row = ctx.create("PORTFOLIO_PHOTO", {"source": source}, technician_id=tech.id)
        result.append(views.media(ctx.store_file(row, data, "image/jpeg", width, height)))
    return result


def case(ctx, tech, body, row=None):
    if row:
        require(row.technician_id == tech.id, "ACCESS_DENIED", "본인 사례만 수정할 수 있습니다.", 403)
        ctx.check_revision(row, body["expectedRevision"])
    value = copy.deepcopy(body["case"])
    owned_media(ctx, tech, [*value["beforeMediaIds"], *value["afterMediaIds"]])
    value["source"] = reference.verified_source(ctx, value["source"], case=value)
    return ctx.save(row, case=value) if row else ctx.create("CASE", {"case": value}, technician_id=tech.id)


def date_bounds(query):
    start_date, end_date = date.fromisoformat(query["from"]), date.fromisoformat(query["to"])
    require(timedelta(0) <= end_date-start_date <= timedelta(days=31), "VALIDATION_ERROR", "일정 조회·편집 범위는 32일 이내여야 합니다.", 422)
    return datetime.combine(start_date, time.min, SEOUL), datetime.combine(end_date+timedelta(days=1), time.min, SEOUL)


def update_schedule(ctx, tech, body):
    row = scheduling.schedule_resource(ctx, tech)
    require(body["expectedRevision"] == (str(row.revision) if row else "0"), "VERSION_CONFLICT", "일정이 변경되었습니다.")
    start, end = date_bounds(body)
    values = scheduling.schedule_data(ctx, tech)
    spans = [interval(r) for r in body["availability"]]
    visits = copy.deepcopy(body["externalVisits"])
    for left, right in spans:
        require(start <= left < right <= end, "VALIDATION_ERROR", "입력 일정은 적용 날짜 범위 안에 있어야 합니다.", 422)
    for i, span in enumerate(spans):
        require(not any(overlap(span, other) for other in spans[i+1:]), "VALIDATION_ERROR", "가능 시간 구간이 중복되었습니다.", 422)
    for visit in visits:
        span = interval(visit["range"])
        require(start <= span[0] < span[1] <= end, "VALIDATION_ERROR", "외부 일정은 적용 범위 안에 있어야 합니다.", 422)
        reservations.validate_location(ctx, visit["locationId"])
        visit["externalVisitId"] = visit.get("externalVisitId") or uid()
    require(len({v["externalVisitId"] for v in visits}) == len(visits), "INVALID_REFERENCE", "외부 일정 ID가 중복되었습니다.", 422)
    for i, visit in enumerate(visits):
        require(not any(overlap(interval(visit["range"]), interval(v["range"])) for v in visits[i+1:]), "TECHNICIAN_CONFLICT", "외부 일정이 충돌합니다.")
    # Preserve entries outside the edited date range; reject partial replacement.
    def outside(span):
        pair = interval(span)
        require(not overlap(pair, (start, end)) or start <= pair[0] < pair[1] <= end,
                "VALIDATION_ERROR", "경계에 걸친 기존 일정의 날짜 전체를 편집하세요.", 422)
        return not overlap(pair, (start, end))
    values["availability"] = [r for r in values["availability"] if outside(r)] + body["availability"]
    values["externalVisits"] = [r for r in values["externalVisits"] if outside(r["range"])] + visits
    for reservation in ctx.find("RESERVATION", technician_id=tech.id):
        if reservation.status in ACTIVE_RESERVATIONS:
            left, right = scheduling.reservation_range(reservation)
            scheduling.check_schedule(ctx, tech, left, right, reservation.data["agreement"]["terms"]["region"],
                                      exclude=reservation.id, proposed_schedule=values)
    if row:
        ctx.save(row, **values)
    else:
        ctx.create("SCHEDULE", values, technician_id=tech.id)
    return schedule_view(ctx, tech, body)


def schedule_view(ctx, tech, query):
    start, end = date_bounds(query)
    row = scheduling.schedule_resource(ctx, tech)
    values = scheduling.schedule_data(ctx, tech)
    active = [r for r in ctx.find("RESERVATION", technician_id=tech.id)
              if overlap(scheduling.reservation_range(r), (start, end))]
    availability = [r for r in values["availability"] if overlap(interval(r), (start, end))]
    visits = [v for v in values["externalVisits"] if overlap(interval(v["range"]), (start, end))]
    checks = [check for r in active for check in reservations.checks(ctx, r)]
    segments, open_ranges = [], []
    for window in availability:
        left, right = interval(window)
        stops = [(scheduling.reservation_range(r), scheduling.effective_location(ctx, r), "RESERVATION", r.id)
                 for r in active if r.status in ACTIVE_RESERVATIONS and overlap(scheduling.reservation_range(r), (left, right))]
        stops += [(interval(v["range"]), v["locationId"], "EXTERNAL_VISIT", v["externalVisitId"]) for v in visits if overlap(interval(v["range"]), (left, right))]
        stops.sort(key=lambda stop: stop[0][0])
        previous = ((left, left), values["departureLocationId"], "DEPARTURE", None)
        for following in [*stops, ((right, right), values["returnLocationId"], "RETURN", None)]:
            issues = []
            try:
                minutes = scheduling.travel_minutes(ctx, previous[1], following[1])
                departure = previous[0][1]
                arrival = departure+timedelta(minutes=minutes)
                if arrival > following[0][0]:
                    issues.append({"status": "CONFLICT", "code": "TECHNICIAN_CONFLICT", "reason": "이동시간이 부족합니다.", "reservationIds": []})
                elif arrival < following[0][0]:
                    open_ranges.append({"startAt": iso(arrival), "endAt": iso(following[0][0])})
            except DomainError:
                minutes = departure = arrival = None
                issues.append({"status": "RECHECK_REQUIRED", "code": "REFERENCE_DATA_MISSING", "reason": "대표 위치 또는 고정 이동시간 미확인", "reservationIds": []})
            segments.append({"from": {"type": previous[2], "resourceId": previous[3], "locationId": previous[1]},
                             "to": {"type": following[2], "resourceId": following[3], "locationId": following[1]},
                             "departureAt": iso(departure) if departure else None, "arrivalAt": iso(arrival) if arrival else None,
                             "minutes": minutes, "checks": issues, "referenceVersions": reference.versions(ctx)})
            previous = following
    return {"revision": str(row.revision) if row else "0", "availability": availability, "externalVisits": visits,
            "reservations": [reservations.view(ctx, r) for r in active], "travelSegments": segments,
            "departureLocationId": values["departureLocationId"], "returnLocationId": values["returnLocationId"],
            "checks": checks, "openRanges": open_ranges, "referenceVersions": reference.versions(ctx)}


def candidates(ctx, item):
    root = ctx.open_request(item)
    reference.require_supported(ctx, root, item)
    require(item.data["reviewStatus"] == "CONFIRMED", "CONFIRMATION_REQUIRED", "요약과 분야를 먼저 확인하세요.")
    region = reference.region(ctx, root.data["region"])
    result = []
    for tech in ctx.find("TECHNICIAN"):
        matched = set(tech.data["profile"]["fields"]) & set(item.data["facts"]["fields"])
        if tech.owner_id == root.owner_id or not matched or region["regionId"] not in tech.data["profile"]["regionIds"]:
            continue
        fit, _, reason = scheduling.candidate_fit(ctx, item, tech)
        result.append({"technician": views.public_technician(ctx, tech), "matchedFields": sorted(matched),
                       "unsupportedFields": sorted(set(item.data["facts"]["fields"])-matched), "timeFit": fit,
                       "durationEstimate": reference.duration(ctx, item), "checks": [] if reason is None else [
                           {"status": "RECHECK_REQUIRED" if fit == "UNKNOWN" else "CONFLICT", "code": "CANDIDATE_SCHEDULE", "reason": reason, "reservationIds": []}]})
    return sorted(result, key=lambda v: (v["timeFit"] != "MATCHED", v["technician"]["technicianId"]))


def candidate_id(ctx, item, tech):
    value = f"{tech.id}:{item.id}:{item.data['sourceRevision']}".encode()
    digest = hmac.new(ctx.settings.session_secret.get_secret_value().encode(), value, hashlib.sha256).hexdigest()[:32]
    return f"{item.id}.{digest}"


def route_candidates(ctx, tech, query):
    results = []
    for item in ctx.find("WORK_ITEM"):
        if not item.data["routeExplorationEnabled"] or item.data["reviewStatus"] != "CONFIRMED" or item.owner_id == tech.owner_id or item.data["activeReservationId"]:
            continue
        root = ctx.get(item.request_id, "REQUEST")
        region = reference.region(ctx, root.data.get("region"))
        if root.status != "OPEN" or not region or region["regionId"] not in tech.data["profile"]["regionIds"]:
            continue
        if not set(item.data["facts"]["fields"]) <= set(tech.data["profile"]["fields"]):
            continue
        fit, route, reason = scheduling.candidate_fit(ctx, item, tech, query["date"])
        if fit == "NOT_MATCHED":
            continue
        results.append({"candidateId": candidate_id(ctx, item, tech), "fields": item.data["facts"]["fields"],
                        "region": region, "visitPreference": item.data["facts"]["visitPreference"],
                        "durationEstimate": reference.duration(ctx, item), "timeFit": fit, "route": route, "reason": reason})
    return sorted(results, key=lambda v: (v["route"] is None, v["route"]["additionalMinutes"] if v["route"] else 0, v["candidateId"]))


def route_sort_key(ctx, value):
    item = ctx.get(value["candidateId"].split(".")[0], "WORK_ITEM")
    root = ctx.get(item.request_id, "REQUEST")
    group = 0 if value["route"] else 1 if value["timeFit"] == "MATCHED" else 2
    return [group, value["route"]["additionalMinutes"] if value["route"] else 0,
            as_utc(root.created_at).timestamp(), value["candidateId"]]


def interest(ctx, identifier):
    tech = ctx.technician()
    item = ctx.get(identifier.split(".")[0], "WORK_ITEM")
    require(hmac.compare_digest(identifier, candidate_id(ctx, item, tech)) and item.data["routeExplorationEnabled"], "RESOURCE_NOT_FOUND", "유효한 동선 후보가 아닙니다.", 404)
    ctx.no_self(item, tech.id)
    ctx.open_request(item)
    row = ctx.create("INTEREST", {"candidateId": identifier}, item_id=item.id, request_id=item.request_id,
                     technician_id=tech.id, owner_id=item.owner_id)
    return {"interestId": row.id, "candidateId": identifier, "technician": views.public_technician(ctx, tech), "createdAt": iso(row.created_at)}
