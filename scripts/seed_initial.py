"""개발 DB에 시연용 기사, 예약 기준 자료, 방문 일정과 대표 시나리오 3종 데이터를 적재합니다."""

# ruff: noqa: E402

import argparse
import hashlib
import io
import json
import os
import secrets
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

# 파일 경로로 실행할 때 모듈과 상대 경로의 기준을 백엔드 디렉터리로 맞춥니다.
if __name__ == "__main__" and __spec__ is None and sys.argv[0] != "-":
    backend_dir = Path(__file__).resolve().parents[1]
    os.chdir(backend_dir)
    sys.path.insert(0, str(backend_dir))

from PIL import Image, ImageDraw
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from app.admin import import_references
from app.config import get_settings
from app.contracts import validate_type
from app.db import Account, Job, ReferenceData, Resource, lock, now, session_factory, uid
from app.errors import DomainError
from app.media import FileStore
from app.schema import validate_schema
from app.security import Actor
from app.services import consultations, handover, requests, reservations, technicians
from app.services.accounts import create_account
from app.services.context import Context
from app.time_rules import SEOUL, iso


SEED_VERSION = "demo-initial-v1"
SEED_KIND = "DEMO_SEED"
DEMO_LOGIN = "demo-tech-01"
SCENARIO1_TECH_A_LOGIN = "demo-tech-door-a"
SCENARIO1_TECH_B_LOGIN = "demo-tech-02"
SCENARIO1_TECH_C_LOGIN = "demo-tech-door-c"
SCENARIO2_COMPETITOR_USER_LOGIN = "demo-user-hapjeong"
SCENARIO3_USER_LOGIN = "demo-user-seoyeon"
SCENARIO3_TECH_LOGIN = "demo-tech-03"
DEMO_PASSWORD_LOGINS = frozenset({
    DEMO_LOGIN,
    SCENARIO1_TECH_A_LOGIN,
    SCENARIO1_TECH_B_LOGIN,
    SCENARIO1_TECH_C_LOGIN,
    SCENARIO2_COMPETITOR_USER_LOGIN,
    SCENARIO3_USER_LOGIN,
    SCENARIO3_TECH_LOGIN,
})

AVAILABILITY_DAYS = 14
THURSDAY = 3
SATURDAY = 5
SHIFTS = ((9, 18), (10, 19), (11, 20))
REGIONS = (
    ("yeonnam", "마포구", "연남동"),
    ("seogyo", "마포구", "서교동"),
    ("hapjeong", "마포구", "합정동"),
    ("yeonhui", "서대문구", "연희동"),
    ("sinchon", "서대문구", "신촌동"),
    ("hyochang", "용산구", "효창동"),
)


@dataclass(frozen=True)
class DemoWork:
    field: str
    name: str
    minutes: int
    symptom: str
    description: str
    confirmed_cause: str | None = None
    parts: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScenarioDoorTech:
    login: str
    source_key: str
    display_name: str
    case_title: str
    symptom: str
    confirmed_cause: str
    description: str
    parts: tuple[str, ...]
    color: tuple[int, int, int]
    visit_kind: str | None = None


WORKS = (
    DemoWork(
        "PLUMBING", "수전 교체", 60, "싱크대 수전 아래로 물이 샙니다.",
        "수전을 교체하고 연결부 누수 여부를 확인했습니다.",
        confirmed_cause="수전 카트리지 및 연결 패킹 노후",
        parts=("싱크대 수전",),
    ),
    DemoWork(
        "DOORS_WINDOWS", "창문 잠금장치 교체", 45, "잠기지 않는 창문의 잠금장치가 걸리지 않습니다.",
        "잠기지 않는 창문의 잠금장치를 교체하고 창문 개폐 상태를 확인했습니다.",
        confirmed_cause="창문 잠금장치 파손",
        parts=("창문 잠금장치",),
    ),
    DemoWork(
        "WALLS_WALLPAPER", "벽지 보수", 90, "벽지 이음새가 들떠 있습니다.",
        "들뜬 구역을 보수하고 이음새를 정리했습니다.",
    ),
    DemoWork(
        "ELECTRICAL", "조명 교체", 45, "천장 조명이 간헐적으로 깜박입니다.",
        "조명을 교체하고 점등 상태를 확인했습니다.",
    ),
    DemoWork(
        "APPLIANCES", "세탁기 배수 점검", 60, "세탁이 끝난 뒤 물이 남아 있습니다.",
        "배수 경로를 점검하고 배수 동작을 확인했습니다.",
    ),
)

EXTRA_DURATIONS = (
    ("sliding-door", "미닫이문 수리", 60),
    ("wallpaper-stain", "벽지 물자국 점검", 60),
)

SCENARIO1_DOOR_TECHS = (
    ScenarioDoorTech(
        login=SCENARIO1_TECH_A_LOGIN,
        source_key="source-door-a",
        display_name="연남동 미닫이문 롤러 시연 기사 A",
        case_title="미닫이문 하부 롤러 교체 모의 사례",
        symptom="닫힘 직전에 바닥을 긁으며 걸리던 거실 미닫이문.",
        confirmed_cause="하부 롤러 마모",
        description="현장에서 하부 롤러 마모를 확인하고 하부 롤러를 교체한 뒤 바닥 간격과 개폐를 점검했습니다.",
        parts=("미닫이문 하부 롤러",),
        color=(56, 114, 102),
        visit_kind=None,
    ),
    ScenarioDoorTech(
        login=SCENARIO1_TECH_C_LOGIN,
        source_key="source-door-c",
        display_name="연남동 미닫이문 레일 시연 기사 C",
        case_title="미닫이문 하단 레일 보수 모의 사례",
        symptom="닫힘 직전에 걸리던 미닫이문.",
        confirmed_cause="하단 레일 변형",
        description="변형된 미닫이문 하단 레일을 보수·교정하고 문 개폐 상태를 확인했습니다.",
        parts=("미닫이문 하단 레일",),
        color=(122, 92, 74),
        visit_kind="door_c_saturday",
    ),
)


@dataclass(frozen=True)
class DemoRegion:
    key: str
    id: str
    location: str
    district: str
    neighborhood: str


@dataclass(frozen=True)
class SeedResult:
    available_through: date
    created: bool = False
    schedules_extended: int = 0
    schedules_skipped: int = 0
    scenario_thursday: date | None = None
    scenario_saturday: date | None = None
    generated_password: str | None = field(default=None, repr=False)


class SeedError(RuntimeError):
    pass


def weekday_dates(start, end, weekday):
    days = []
    current = start
    while current <= end:
        if current.weekday() == weekday:
            days.append(current)
        current += timedelta(days=1)
    return days


def next_weekday(today, weekday):
    delta = (weekday - today.weekday()) % 7 or 7
    return today + timedelta(days=delta)


def reference_entry(key, kind, data):
    return {
        "id": f"{SEED_VERSION}-{key}",
        "kind": kind,
        "verified": True,
        "source": "고쳐야집 개발 시연용 모의 자료",
        "data": data,
    }


def insert_references(db, today, entries):
    if not entries:
        return
    ids = [entry["id"] for entry in entries]
    collision = db.scalar(select(ReferenceData.id).where(ReferenceData.id.in_(ids)).limit(1))
    if collision:
        raise SeedError(f"기준 자료 ID {collision}이(가) 이미 사용 중입니다.")
    import_references(db, {
        "version": SEED_VERSION,
        "reviewedBy": "고쳐야집 시연 데이터",
        "reviewedAt": today.isoformat(),
        "entries": entries,
    })


def prepare_references(ctx, today):
    existing_regions = {}
    for row in ctx.references("REGION"):
        key = tuple(row.data.get(name) for name in ("city", "district", "neighborhood"))
        existing_regions.setdefault(key, row)

    entries, regions = [], []
    for key, district, neighborhood in REGIONS:
        city = "서울특별시"
        existing = existing_regions.get((city, district, neighborhood))
        if existing:
            location = existing.data.get("representativeLocationId")
            if not isinstance(location, str) or not location:
                raise SeedError(f"{district} {neighborhood}의 대표 위치를 확인하세요.")
            regions.append(DemoRegion(key, existing.id, location, district, neighborhood))
            continue
        location = f"{SEED_VERSION}-location-{key}"
        entry = reference_entry(f"region-{key}", "REGION", {
            "city": city,
            "district": district,
            "neighborhood": neighborhood,
            "representativeLocationId": location,
        })
        entries.append(entry)
        regions.append(DemoRegion(key, entry["id"], location, district, neighborhood))

    travel_pairs = {
        (row.data.get("fromLocationId"), row.data.get("toLocationId"))
        for row in ctx.references("TRAVEL")
    }
    for origin in regions:
        for destination in regions:
            pair = (origin.location, destination.location)
            if pair in travel_pairs:
                continue
            if origin.location == destination.location:
                minutes = 15
            else:
                minutes = 30 if origin.district == destination.district else 45
            entries.append(reference_entry(f"travel-{origin.key}-{destination.key}", "TRAVEL", {
                "fromLocationId": origin.location,
                "toLocationId": destination.location,
                "minutes": minutes,
            }))
            travel_pairs.add(pair)

    durations = {
        (row.data.get("workType"), row.data.get("quantity"))
        for row in ctx.references("DURATION")
    }
    for work in WORKS:
        if (work.name, 1) not in durations:
            entries.append(reference_entry(f"duration-{work.field.lower()}", "DURATION", {
                "workType": work.name,
                "quantity": 1,
                "minutes": work.minutes,
            }))
            durations.add((work.name, 1))
    for key, work_type, minutes in EXTRA_DURATIONS:
        if (work_type, 1) not in durations:
            entries.append(reference_entry(f"duration-{key}", "DURATION", {
                "workType": work_type,
                "quantity": 1,
                "minutes": minutes,
            }))
            durations.add((work_type, 1))

    insert_references(ctx.db, today, entries)
    return regions


def availability(shift_index, start, end):
    opening, closing = SHIFTS[shift_index % len(SHIFTS)]
    ranges = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        ranges.append({
            "startAt": iso(datetime.combine(day, time(opening), SEOUL)),
            "endAt": iso(datetime.combine(day, time(closing), SEOUL)),
        })
    return ranges


def scenario_external_visits(visit_kind, locations, start, end):
    visits = []
    if visit_kind == "route_thursday":
        for day in weekday_dates(start, end, THURSDAY):
            visits.append({
                "externalVisitId": f"{SEED_VERSION}-visit-route-before-{day.isoformat()}",
                "range": {
                    "startAt": iso(datetime.combine(day, time(13, 0), SEOUL)),
                    "endAt": iso(datetime.combine(day, time(13, 45), SEOUL)),
                },
                "locationId": locations["yeonnam"],
                "description": "기존 방문 · 연남동 수전 점검",
            })
            visits.append({
                "externalVisitId": f"{SEED_VERSION}-visit-route-after-{day.isoformat()}",
                "range": {
                    "startAt": iso(datetime.combine(day, time(16, 0), SEOUL)),
                    "endAt": iso(datetime.combine(day, time(16, 45), SEOUL)),
                },
                "locationId": locations["seogyo"],
                "description": "다음 방문 · 서교동 배관 점검",
            })
    elif visit_kind == "door_c_saturday":
        for day in weekday_dates(start, end, SATURDAY):
            visits.append({
                "externalVisitId": f"{SEED_VERSION}-visit-door-c-{day.isoformat()}",
                "range": {
                    "startAt": iso(datetime.combine(day, time(14, 0), SEOUL)),
                    "endAt": iso(datetime.combine(day, time(17, 0), SEOUL)),
                },
                "locationId": locations["yeonnam"],
                "description": "기존 작업 · 연남동 문·창호 수리",
            })
    for visit in visits:
        validate_type(visit, "ExternalVisitDTO", "externalVisit")
    return visits


def synthetic_image(color, repaired):
    with Image.new("RGB", (320, 240), (239, 241, 244)) as image, io.BytesIO() as buffer:
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((44, 48, 276, 192), radius=16, fill=color)
        draw.line((102, 120, 218, 120), fill="white", width=8)
        if not repaired:
            draw.ellipse((140, 138, 180, 178), fill=(192, 59, 59))
        image.save(buffer, "PNG")
        return buffer.getvalue()


def sliding_door_image(color, repaired):
    with Image.new("RGB", (320, 240), (242, 240, 235)) as image, io.BytesIO() as buffer:
        draw = ImageDraw.Draw(image)
        draw.rectangle((28, 24, 292, 196), outline=(110, 114, 120), width=4, fill=(228, 232, 236))
        draw.rectangle((48, 34, 184, 188), fill=color, outline=(70, 74, 80), width=3)
        draw.rectangle((28, 188, 292, 206), fill=(156, 160, 166))
        if not repaired:
            draw.line((170, 192, 248, 198), fill=(188, 56, 56), width=5)
            draw.ellipse((150, 178, 174, 202), fill=(188, 56, 56))
        else:
            draw.ellipse((150, 178, 174, 202), fill=(62, 148, 102))
            draw.line((34, 196, 286, 196), fill=(230, 234, 238), width=3)
        image.save(buffer, "PNG")
        return buffer.getvalue()


def wallpaper_stain_image(stage):
    if stage == "night_closeup":
        with Image.new("RGB", (320, 240), (92, 84, 74)) as image, io.BytesIO() as buffer:
            draw = ImageDraw.Draw(image)
            draw.ellipse((74, 46, 254, 198), fill=(70, 61, 52))
            draw.ellipse((110, 78, 224, 172), fill=(58, 50, 42))
            image.save(buffer, "PNG")
            return buffer.getvalue()
    with Image.new("RGB", (320, 240), (238, 233, 222)) as image, io.BytesIO() as buffer:
        draw = ImageDraw.Draw(image)
        draw.rectangle((148, 18, 304, 118), fill=(250, 250, 250), outline=(176, 182, 188), width=6)
        draw.line((226, 18, 226, 118), fill=(176, 182, 188), width=4)
        if stage == "baseline":
            draw.ellipse((78, 122, 146, 158), fill=(204, 188, 162))
        else:
            draw.ellipse((70, 122, 156, 212), fill=(178, 154, 122))
            draw.ellipse((86, 148, 142, 202), fill=(160, 134, 102))
        image.save(buffer, "PNG")
        return buffer.getvalue()


def register_case_portfolio(
    ctx, tech, today, *, source_key, source_title, title, field_name, symptom,
    confirmed_cause, description, parts, images,
):
    source = {
        "title": source_title,
        "reference": f"{SEED_VERSION}-{source_key}",
        "version": SEED_VERSION,
        "verifiedAt": today.isoformat(),
        "usageBasis": "이 스크립트에서 만든 시연용 사례와 합성 이미지",
    }
    entry = reference_entry(source_key, "SOURCE", {
        **source,
        "identifiersRemoved": True,
        "assetSha256": [hashlib.sha256(image).hexdigest() for image in images],
    })
    insert_references(ctx.db, today, [entry])
    before, after = technicians.upload(ctx, tech, [{"bytes": image} for image in images], source)

    content = {
        "title": title,
        "fields": [field_name],
        "initialSymptom": symptom,
        "confirmedCause": confirmed_cause,
        "workDescription": description,
        "parts": list(parts),
        "beforeMediaIds": [before["mediaId"]],
        "afterMediaIds": [after["mediaId"]],
        "dataType": "MOCK",
    }
    # 사례 검증은 출처를 제외한 최종 본문과 업로드에서 발급된 미디어 ID를 포함한다.
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    row = ctx.db.get(ReferenceData, entry["id"])
    row.data = {**row.data, "caseSha256": [hashlib.sha256(encoded.encode()).hexdigest()]}
    case = {**content, "source": source}
    validate_type(case, "CaseContentDTO", "case")
    technicians.case(ctx, tech, {"case": case})
    return [after["mediaId"]]


def add_portfolio(ctx, tech, work, today, index):
    colors = ((38, 105, 138), (88, 102, 131), (132, 112, 90), (144, 109, 43), (45, 118, 106))
    images = [synthetic_image(colors[index], repaired) for repaired in (False, True)]
    return register_case_portfolio(
        ctx, tech, today,
        source_key=f"source-{work.field.lower()}",
        source_title=f"고쳐야집 모의 자료 · {work.name}",
        title=f"{work.name} 모의 사례",
        field_name=work.field,
        symptom=work.symptom,
        confirmed_cause=work.confirmed_cause,
        description=work.description,
        parts=work.parts,
        images=images,
    )


def create_technicians(ctx, regions, today, through, demo_password):
    by_key = {region.key: region for region in regions}
    base_logins = [f"demo-tech-{index:02}" for index in range(1, len(regions) * len(WORKS) + 1)]
    scenario_logins = [item.login for item in SCENARIO1_DOOR_TECHS]
    all_logins = base_logins + scenario_logins
    collision = ctx.db.scalar(select(Account.login_id).where(Account.login_id.in_(all_logins)).limit(1))
    if collision:
        raise SeedError(f"기사 로그인 ID {collision}이(가) 이미 사용 중입니다.")

    schedules, tech_by_login = [], {}
    for index, login in enumerate(base_logins):
        region_index, work_index = divmod(index, len(WORKS))
        region, work = regions[region_index], WORKS[work_index]
        password = demo_password if login in DEMO_PASSWORD_LOGINS else secrets.token_urlsafe(24)
        account = create_account(ctx.db, ctx.settings, login, password, ["USER", "TECHNICIAN"])
        tech = ctx.db.scalar(select(Resource).where(
            Resource.kind == "TECHNICIAN", Resource.owner_id == account.id,
        ))
        owner = Context(
            ctx.db, Actor(account.id, "TECHNICIAN", tech.id, None), ctx.settings,
            new_files=ctx.new_files,
        )
        media_ids = add_portfolio(owner, tech, work, today, work_index) if region_index == 0 else []
        region_ids = [region.id]
        if index % 3 == 0:
            region_ids.append(regions[(region_index + 1) % len(regions)].id)
        if login == DEMO_LOGIN and by_key["hapjeong"].id not in region_ids:
            region_ids.append(by_key["hapjeong"].id)
        profile = {
            "displayName": f"{region.neighborhood} {work.name} 시연 기사",
            "fields": [work.field],
            "regionIds": region_ids,
            "contacts": [{
                "contact": {"label": "시연용 문의", "value": f"https://demo.example.invalid/{login}"},
                "isPublic": True,
            }],
            "representativeMediaIds": media_ids,
        }
        validate_type(profile, "TechnicianProfileContentDTO", "profile")
        technicians.profile(owner, tech, {
            "expectedRevision": str(tech.revision),
            "profile": profile,
        })
        visit_kind = "route_thursday" if login == DEMO_LOGIN else None
        locations = (
            {"yeonnam": by_key["yeonnam"].location, "seogyo": by_key["seogyo"].location}
            if visit_kind else {}
        )
        schedule = owner.create("SCHEDULE", {
            "availability": availability(index, today, through),
            "externalVisits": scenario_external_visits(visit_kind, locations, today, through),
            "departureLocationId": region.location,
            "returnLocationId": region.location,
        }, technician_id=tech.id)
        schedules.append({
            "id": schedule.id,
            "revision": schedule.revision,
            "shiftIndex": index % len(SHIFTS),
            "visitKind": visit_kind,
            "locations": locations,
        })
        tech_by_login[login] = (account, tech)

    yeonnam = by_key["yeonnam"]
    for item in SCENARIO1_DOOR_TECHS:
        account = create_account(ctx.db, ctx.settings, item.login, demo_password, ["USER", "TECHNICIAN"])
        tech = ctx.db.scalar(select(Resource).where(
            Resource.kind == "TECHNICIAN", Resource.owner_id == account.id,
        ))
        owner = Context(
            ctx.db, Actor(account.id, "TECHNICIAN", tech.id, None), ctx.settings,
            new_files=ctx.new_files,
        )
        images = [sliding_door_image(item.color, repaired) for repaired in (False, True)]
        media_ids = register_case_portfolio(
            owner, tech, today,
            source_key=item.source_key,
            source_title=f"고쳐야집 모의 자료 · {item.case_title}",
            title=item.case_title,
            field_name="DOORS_WINDOWS",
            symptom=item.symptom,
            confirmed_cause=item.confirmed_cause,
            description=item.description,
            parts=item.parts,
            images=images,
        )
        profile = {
            "displayName": item.display_name,
            "fields": ["DOORS_WINDOWS"],
            "regionIds": [yeonnam.id],
            "contacts": [{
                "contact": {"label": "시연용 문의", "value": f"https://demo.example.invalid/{item.login}"},
                "isPublic": True,
            }],
            "representativeMediaIds": media_ids,
        }
        validate_type(profile, "TechnicianProfileContentDTO", "profile")
        technicians.profile(owner, tech, {
            "expectedRevision": str(tech.revision),
            "profile": profile,
        })
        locations = {"yeonnam": yeonnam.location} if item.visit_kind else {}
        schedule = owner.create("SCHEDULE", {
            "availability": availability(0, today, through),
            "externalVisits": scenario_external_visits(item.visit_kind, locations, today, through),
            "departureLocationId": yeonnam.location,
            "returnLocationId": yeonnam.location,
        }, technician_id=tech.id)
        schedules.append({
            "id": schedule.id,
            "revision": schedule.revision,
            "shiftIndex": 0,
            "visitKind": item.visit_kind,
            "locations": locations,
        })
        tech_by_login[item.login] = (account, tech)

    return schedules, tech_by_login


def seed_scenario_requests(ctx, regions, today, through, demo_password, tech_by_login):
    scenario_users = [SCENARIO2_COMPETITOR_USER_LOGIN, SCENARIO3_USER_LOGIN]
    collision = ctx.db.scalar(select(Account.login_id).where(Account.login_id.in_(scenario_users)).limit(1))
    if collision:
        raise SeedError(f"시연 사용자 로그인 ID {collision}이(가) 이미 사용 중입니다.")

    by_key = {region.key: region for region in regions}

    # 시나리오 2 비교용: 합정동 수전 교체 요청 (목요일 14:00~17:00, 동선 제안 탐색 활성)
    hapjeong_account = create_account(
        ctx.db, ctx.settings, SCENARIO2_COMPETITOR_USER_LOGIN, demo_password, ["USER"],
    )
    hapjeong_ctx = Context(
        ctx.db, Actor(hapjeong_account.id, "USER", None, None), ctx.settings,
        new_files=ctx.new_files,
    )
    hapjeong = by_key["hapjeong"]
    thursdays = weekday_dates(today + timedelta(days=1), through, THURSDAY)
    hapjeong_root = requests.create_request(
        hapjeong_ctx,
        {
            "symptom": "합정동 싱크대 수전 한 개를 교체하려고 합니다. 목요일 오후 중 한 시간 방문 가능합니다.",
            "region": {
                "city": "서울특별시",
                "district": hapjeong.district,
                "neighborhood": hapjeong.neighborhood,
                "regionId": hapjeong.id,
            },
            "photos": [{
                "capturedOn": today.isoformat(),
                "dateConfirmed": True,
                "description": "합정동 싱크대 수전 사진",
            }],
        },
        [{"bytes": synthetic_image((38, 105, 138), False)}],
    )
    hapjeong_item = hapjeong_ctx.find("WORK_ITEM", request_id=hapjeong_root.id)[0]
    requests.patch_item(hapjeong_ctx, hapjeong_item, {
        "expectedRevision": str(hapjeong_item.revision),
        "facts": {
            "part": "싱크대 수전",
            "workType": "수전 교체",
            "quantity": 1,
            "fields": ["PLUMBING"],
            "visitPreference": {
                "mode": "FLEXIBLE",
                "fixedStartAt": None,
                "ranges": [
                    {
                        "startAt": iso(datetime.combine(day, time(14, 0), SEOUL)),
                        "endAt": iso(datetime.combine(day, time(17, 0), SEOUL)),
                    }
                    for day in thursdays
                ],
            },
        },
        "resolutionPath": "TECHNICIAN",
    })
    requests.confirm_item(hapjeong_ctx, hapjeong_item, {
        "expectedRevision": str(hapjeong_item.revision),
        "sourceRevision": hapjeong_item.data["sourceRevision"],
        "fields": ["PLUMBING"],
        "confirmed": True,
        "summary": {
            "text": "사용자 진술: 합정동 싱크대 수전 1개 교체 요청. 현장 조건은 방문 확인 필요.",
            "facts": [],
            "unknowns": ["기존 수전 규격 및 배관 상태"],
            "riskSignals": [],
            "limitations": ["시연용 비교 요청 자료"],
            "onsiteInspectionNeeded": True,
        },
    })
    hapjeong_ctx.save(hapjeong_item, routeExplorationEnabled=True)

    # 시나리오 3: 서연의 벽지 물자국 경과 기록 + 확정 예약 (벽면·도배 기사 demo-tech-03)
    seoyeon_account = create_account(
        ctx.db, ctx.settings, SCENARIO3_USER_LOGIN, demo_password, ["USER"],
    )
    seoyeon_ctx = Context(
        ctx.db, Actor(seoyeon_account.id, "USER", None, None), ctx.settings,
        new_files=ctx.new_files,
    )
    yeonnam = by_key["yeonnam"]
    day1 = (today - timedelta(days=7)).isoformat()
    day3 = (today - timedelta(days=5)).isoformat()
    day4 = (today - timedelta(days=4)).isoformat()
    seoyeon_root = requests.create_request(
        seoyeon_ctx,
        {
            "symptom": "거실 창문 왼쪽 아래 벽지 물자국이 커진 것 같아 집주인과 점검 일정을 의논하고 기사님께 경과를 전달하려고 합니다.",
            "context": {
                "locationDescription": "거실 창문 왼쪽 아래 벽지",
                "discoveredOn": day1,
                "conditions": "비가 온 날 이후 자국이 더 짙어 보이고 환기 후에도 남음",
                "recurring": True,
                "attemptedActions": ["저녁 시간 창문 환기"],
            },
            "region": {
                "city": "서울특별시",
                "district": yeonnam.district,
                "neighborhood": yeonnam.neighborhood,
                "regionId": yeonnam.id,
            },
            "photos": [
                {
                    "capturedOn": day1,
                    "dateConfirmed": True,
                    "description": "08:00 촬영. 옅은 물자국을 처음 발견. 창틀과 벽지 경계가 함께 보이도록 촬영.",
                },
                {
                    "capturedOn": day3,
                    "dateConfirmed": True,
                    "description": "21:00 촬영. 비가 온 날 밤, 가까이서 촬영. 저녁에 환기했다고 기록.",
                },
                {
                    "capturedOn": day4,
                    "dateConfirmed": True,
                    "description": "08:00 촬영. 첫날과 비슷한 거리·구도로 촬영. 물자국의 아래쪽 경계가 더 넓어 보임.",
                },
            ],
        },
        [
            {"bytes": wallpaper_stain_image("baseline")},
            {"bytes": wallpaper_stain_image("night_closeup")},
            {"bytes": wallpaper_stain_image("expanded")},
        ],
    )
    seoyeon_item = seoyeon_ctx.find("WORK_ITEM", request_id=seoyeon_root.id)[0]
    seoyeon_photos = sorted(
        seoyeon_ctx.find("PHOTO", request_id=seoyeon_root.id),
        key=lambda row: (row.data["capturedOn"], row.id),
    )
    record_entries = (
        (day1, "08:00 옅은 물자국을 처음 발견. 창틀과 벽지 경계가 함께 보이도록 촬영.", seoyeon_photos[0].id),
        (day3, "21:00 비가 온 날 밤, 가까이서 촬영. 저녁에 환기했으나 자국이 남음.", seoyeon_photos[1].id),
        (day4, "08:00 첫날과 비슷한 거리·구도로 촬영. 물자국의 아래쪽 경계가 더 넓어 보임.", seoyeon_photos[2].id),
    )
    for occurred_on, description, photo_id in record_entries:
        requests.add_record(seoyeon_ctx, seoyeon_root, {
            "record": {
                "occurredOn": occurred_on,
                "description": description,
                "photoIds": [photo_id],
                "workItemIds": [seoyeon_item.id],
            },
        })
    requests.set_groups(seoyeon_ctx, seoyeon_root, {
        "sourceRevision": seoyeon_root.data["sourceRevision"],
        "groups": [{
            "label": "거실 창문 왼쪽 아래 벽지 물자국",
            "photoIds": [photo.id for photo in seoyeon_photos],
            "selectedPhotoIds": [],
        }],
    })

    visit_day = today + timedelta(days=3)
    visit_start = datetime.combine(visit_day, time(14, 0), SEOUL)
    requests.patch_item(seoyeon_ctx, seoyeon_item, {
        "expectedRevision": str(seoyeon_item.revision),
        "facts": {
            "part": "거실 창문 왼쪽 아래 벽지",
            "workType": "벽지 물자국 점검",
            "quantity": 1,
            "fields": ["WALLS_WALLPAPER"],
            "visitPreference": {
                "mode": "FLEXIBLE",
                "fixedStartAt": None,
                "ranges": [{
                    "startAt": iso(datetime.combine(visit_day, time(13, 0), SEOUL)),
                    "endAt": iso(datetime.combine(visit_day, time(17, 0), SEOUL)),
                }],
            },
        },
        "resolutionPath": "TECHNICIAN",
    })
    requests.confirm_item(seoyeon_ctx, seoyeon_item, {
        "expectedRevision": str(seoyeon_item.revision),
        "sourceRevision": seoyeon_item.data["sourceRevision"],
        "fields": ["WALLS_WALLPAPER"],
        "confirmed": True,
        "summary": {
            "text": f"사용자 기록 및 관찰: {day1} 최초 발견 이후 {day4} 사진에서 거실 창문 왼쪽 아래 벽지 물자국이 아래쪽으로 넓게 보임. {day3} 비가 온 뒤 환기했으나 자국이 남음. 원인은 현장 점검 필요.",
            "facts": [
                {
                    "text": "1일차와 4일차 동일 구도 사진에서 벽지 물자국 아래쪽 경계가 넓어진 것으로 보임.",
                    "sourceType": "OBSERVATION",
                    "photoIds": [seoyeon_photos[0].id, seoyeon_photos[2].id],
                    "recordIds": [],
                    "performanceReservationIds": [],
                },
                {
                    "text": "비가 온 날 밤 저녁에 환기했으나 자국이 남았다고 사용자가 기록함.",
                    "sourceType": "USER_STATEMENT",
                    "photoIds": [seoyeon_photos[1].id],
                    "recordIds": [],
                    "performanceReservationIds": [],
                },
            ],
            "unknowns": ["벽지 물자국의 내부 원인(외부 창틀 누수·결로 등)"],
            "riskSignals": ["물자국 범위 확대 여부 및 습기 지속 확인 필요"],
            "limitations": ["사진만으로 내부 누수 여부와 원인을 단정할 수 없음"],
            "onsiteInspectionNeeded": True,
        },
    })
    requests.visit_details(seoyeon_ctx, seoyeon_root, {
        "expectedRevision": str(seoyeon_root.revision),
        "confirmed": True,
        "visitDetails": {
            "address": f"서울특별시 {yeonnam.district} {yeonnam.neighborhood} 시연빌라 302호",
            "contact": "010-0000-0302",
        },
    })

    wall_account, wall_tech = tech_by_login[SCENARIO3_TECH_LOGIN]
    wall_ctx = Context(
        ctx.db, Actor(wall_account.id, "TECHNICIAN", wall_tech.id, None), ctx.settings,
        new_files=ctx.new_files,
    )
    delivery = handover.create(seoyeon_ctx, seoyeon_item, {
        "sourceRevision": seoyeon_item.data["sourceRevision"],
        "scope": {
            "purpose": "CONSULTATION",
            "recipientTechnicianId": wall_tech.id,
            "photoIds": [seoyeon_photos[0].id, seoyeon_photos[2].id],
            "recordIds": [],
            "questionIds": [],
            "includeSummary": True,
            "includeReport": False,
            "includeQuoteContext": True,
        },
        "redactions": [],
    })
    delivery_job = ctx.db.get(Job, delivery.id)
    handover.render(seoyeon_ctx, delivery, delivery_job.payload)
    delivery_job.state = "DONE"
    handover.confirm(seoyeon_ctx, delivery, {
        "expectedRevision": str(delivery.revision),
        "sourceRevision": seoyeon_item.data["sourceRevision"],
        "confirmed": True,
    })
    relation = consultations.create(seoyeon_ctx, seoyeon_item, {
        "technicianId": wall_tech.id,
        "deliveryId": delivery.id,
    })
    consultations.change(wall_ctx, relation, {
        "expectedRevision": str(relation.revision),
        "action": "ACCEPT",
    })
    quote = consultations.issue_quote(wall_ctx, relation, {
        "contextDeliveryId": delivery.id,
        "terms": {
            "versions": {
                "commonVersion": seoyeon_root.data["commonVersion"],
                "itemVersion": seoyeon_item.data["itemVersion"],
                "proposalVersion": None,
            },
            "fields": ["WALLS_WALLPAPER"],
            "scope": "거실 창문 왼쪽 아래 벽지 물자국 및 창틀 경계 현장 점검",
            "quantity": 1,
            "durationMinutes": 60,
            "startAt": iso(visit_start),
            "expiresAt": iso(visit_start - timedelta(minutes=30)),
            "cost": {
                "minimumVisitFee": 20000,
                "minimumDiagnosticFee": 10000,
                "lines": [
                    {
                        "category": "VISIT",
                        "description": "출장비",
                        "confirmed": True,
                        "beforeAmount": 20000,
                        "afterAmount": 20000,
                        "condition": None,
                    },
                    {
                        "category": "DIAGNOSIS",
                        "description": "벽지 물자국 및 창틀 경계 점검비",
                        "confirmed": True,
                        "beforeAmount": 10000,
                        "afterAmount": 10000,
                        "condition": None,
                    },
                    {
                        "category": "ADDITIONAL_WORK",
                        "description": "원인 확인 후 보수 작업",
                        "confirmed": False,
                        "beforeAmount": None,
                        "afterAmount": None,
                        "condition": "현장 점검 후 실리콘 보수 또는 부분 도배 필요 시 별도 합의",
                    },
                ],
                "discountCondition": None,
            },
        },
    })
    reservations.create(seoyeon_ctx, seoyeon_item, {
        "quoteId": quote.id,
        "versions": quote.data["terms"]["versions"],
        "visitDetailsRevision": seoyeon_root.data["visitDetailsRevision"],
    })


def extend_schedules(ctx, manifest, today, through):
    if manifest.kind != SEED_KIND or manifest.version != SEED_VERSION or manifest.verified:
        raise SeedError(f"기준 자료 ID {SEED_VERSION}이(가) 이미 사용 중입니다.")
    last_day = date.fromisoformat(manifest.data["availableThrough"])
    if last_day >= through:
        return SeedResult(
            last_day,
            scenario_thursday=next_weekday(today, THURSDAY),
            scenario_saturday=next_weekday(today, SATURDAY),
        )

    start = max(today, last_day + timedelta(days=1))
    schedules, extended = [], 0
    for index, entry in enumerate(manifest.data["schedules"]):
        row = ctx.db.get(Resource, entry["id"])
        if (
            row and row.kind == "SCHEDULE" and not row.deleting
            and row.revision == entry["revision"]
        ):
            shift_index = entry.get("shiftIndex", index % len(SHIFTS))
            new_days = availability(shift_index, start, through)
            new_visits = scenario_external_visits(
                entry.get("visitKind"), entry.get("locations") or {}, start, through,
            )
            ctx.save(
                row,
                availability=[*row.data["availability"], *new_days],
                externalVisits=[*row.data["externalVisits"], *new_visits],
            )
            entry = {**entry, "revision": row.revision}
            extended += 1
        schedules.append(entry)
    manifest.data = {"availableThrough": through.isoformat(), "schedules": schedules}
    return SeedResult(
        through,
        schedules_extended=extended,
        schedules_skipped=len(schedules) - extended,
        scenario_thursday=next_weekday(today, THURSDAY),
        scenario_saturday=next_weekday(today, SATURDAY),
    )


def seed_initial(settings, factory, today=None):
    if settings.environment not in ("development", "test"):
        raise SeedError("초기 시연 데이터는 development 또는 test 환경에서 적재할 수 있습니다.")
    today = today or now().astimezone(SEOUL).date()
    through = today + timedelta(days=AVAILABILITY_DAYS - 1)
    created_files = []
    try:
        with factory.begin() as db:
            if db.bind.dialect.name == "sqlite":
                db.execute(text("BEGIN IMMEDIATE"))
            lock(db, "admin")
            validate_schema(db.connection())
            ctx = Context(db, None, settings, new_files=created_files)
            manifest = db.get(ReferenceData, SEED_VERSION)
            if manifest:
                return extend_schedules(ctx, manifest, today, through)

            configured_password = settings.seed_password.get_secret_value()
            password = configured_password or secrets.token_urlsafe(24)
            regions = prepare_references(ctx, today)
            schedules, tech_by_login = create_technicians(ctx, regions, today, through, password)
            seed_scenario_requests(ctx, regions, today, through, password, tech_by_login)
            db.add(ReferenceData(
                id=SEED_VERSION,
                kind=SEED_KIND,
                version=SEED_VERSION,
                verified=False,
                data={"availableThrough": through.isoformat(), "schedules": schedules},
            ))
            return SeedResult(
                through,
                created=True,
                scenario_thursday=next_weekday(today, THURSDAY),
                scenario_saturday=next_weekday(today, SATURDAY),
                generated_password=password if not configured_password else None,
            )
    except (Exception, KeyboardInterrupt):
        store = FileStore(settings.storage_dir)
        for key in created_files:
            store.delete(key)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        result = seed_initial(get_settings(), session_factory())
    except RuntimeError as error:
        parser.exit(1, f"초기 적재 실패. {error}\n")
    except DomainError as error:
        parser.exit(1, f"초기 적재 실패. {error.message}\n")
    except SQLAlchemyError:
        parser.exit(1, "초기 적재 실패. DB 연결 설정과 마이그레이션 상태를 확인하세요.\n")
    except OSError:
        parser.exit(1, "초기 적재 실패. 미디어 저장 경로의 쓰기 권한을 확인하세요.\n")

    total_technicians = len(REGIONS) * len(WORKS) + len(SCENARIO1_DOOR_TECHS)
    total_cases = len(WORKS) + len(SCENARIO1_DOOR_TECHS)
    if result.created:
        print(
            f"기사 {total_technicians}명, 예약 기준 자료, 모의 사례 {total_cases}건과 "
            "대표 시연 시나리오 3종 데이터를 적재했습니다."
        )
    elif result.schedules_extended or result.schedules_skipped:
        print(f"기사 일정 {result.schedules_extended}건을 연장했습니다.")
        if result.schedules_skipped:
            print(f"적재 후 변경된 일정 {result.schedules_skipped}건은 연장 대상에서 제외했습니다.")
    else:
        print("오늘 기준 초기 시연 데이터가 준비되어 있습니다.")
    print(f"시연 일정은 {result.available_through}까지입니다. (한국 시간)")
    if result.scenario_saturday:
        print(f"시나리오 1 기준 토요일: {result.scenario_saturday} (기사 A {SCENARIO1_TECH_A_LOGIN}, B {SCENARIO1_TECH_B_LOGIN}, C {SCENARIO1_TECH_C_LOGIN})")
    if result.scenario_thursday:
        print(f"시나리오 2 기준 목요일: {result.scenario_thursday} (기사 {DEMO_LOGIN}, 비교 요청 {SCENARIO2_COMPETITOR_USER_LOGIN})")
    print(f"시나리오 3 계정: 임차인 {SCENARIO3_USER_LOGIN}, 확정 예약 기사 {SCENARIO3_TECH_LOGIN}")
    if result.generated_password:
        print(f"이번에 발급한 공용 시연 비밀번호 {result.generated_password}")


if __name__ == "__main__":
    main()
