"""개발 DB에 시연용 기사, 예약 기준 자료, 방문 일정과 대표 시나리오 3종 데이터를 적재합니다."""

# ruff: noqa: E402

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from pathlib import Path

# 파일 경로로 실행할 때 모듈과 상대 경로의 기준을 백엔드 디렉터리로 맞춥니다.
if __name__ == "__main__" and __spec__ is None and sys.argv[0] != "-":
    backend_dir = Path(__file__).resolve().parents[1]
    os.chdir(backend_dir)
    sys.path.insert(0, str(backend_dir))

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from app.admin import import_references
from app.config import get_settings
from app.contracts import validate_type
from app.db import Account, Job, ReferenceData, Resource, StoredFile, lock, now, session_factory, uid
from app.errors import DomainError
from app.media import FileStore, mask_image, normalize_image
from app.schema import validate_schema
from app.security import Actor, hash_password, verify_password
from app.services import consultations, handover, requests, reservations, technicians, views
from app.services.accounts import create_account
from app.services.context import Context
from app.time_rules import SEOUL, iso


SEED_VERSION = "demo-initial-v1"
SCENARIO_SEED_VERSION = 3
PHOTO_SEED_VERSION = 1
SEED_KIND = "DEMO_SEED"
SEED_PHOTO_USAGE = "시연용 모의 사례와 AI 이미지 모델로 생성한 사진"
SEED_IMAGE_DIR = Path(__file__).resolve().parent / "seed_images"
if __file__ == "<stdin>":
    SEED_IMAGE_DIR = Path.cwd() / "scripts" / "seed_images"

DEMO_PASSWORD = "432!"
DEMO_LOGIN = "demo-tech-01"
SCENARIO1_USER_LOGIN = "demo-user-minseo"
SCENARIO1_TECH_A_LOGIN = "demo-tech-door-a"
SCENARIO1_TECH_B_LOGIN = "demo-tech-02"
SCENARIO1_TECH_C_LOGIN = "demo-tech-door-c"
SCENARIO2_USER_LOGIN = "demo-user-jihoon"
SCENARIO2_COMPETITOR_USER_LOGIN = "demo-user-hapjeong"
SCENARIO3_USER_LOGIN = "demo-user-seoyeon"
SCENARIO3_TECH_LOGIN = "demo-tech-03"
SCENARIO3_QUOTE_SCOPE = "거실 창문 왼쪽 아래 벽지 물자국 및 창틀 경계 현장 점검"
SCENARIO_USER_LOGINS = (
    SCENARIO1_USER_LOGIN,
    SCENARIO2_USER_LOGIN,
    SCENARIO2_COMPETITOR_USER_LOGIN,
    SCENARIO3_USER_LOGIN,
)

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

# 이전 시드의 도형 그림을 업로드 경로에서 JPEG로 정규화한 뒤의 해시입니다.
LEGACY_PHOTO_SHA256 = {
    "faucet-before": "35db263799bd52f15736dd54c9c267b3b384fa89c788a7b2a528bfea24a653b4",
    "faucet-after": "f3b0591e1e676a25abd03b97f6fdda56310053bea9f8fe85a2bf07b682722a67",
    "window-lock-before": "c7aaaac2390e1bbf390419735cf9b975c766c1a062cc882b9785aac86b38735b",
    "window-lock-after": "7ec15445ce85868c83d71c7b265a50596aba897e5a7ef0b998317a9feb4a46ff",
    "wallpaper-seam-before": "dfdf1fd4bd05abeed6e4549aa4c33aa8931b744d25d41668e03901e13beae000",
    "wallpaper-seam-after": "490eb7d3e654b9fd1897e69cb558bfc1dd09e78683037f33b894611ed13e4600",
    "lighting-before": "5654a12713f052eee23175ef1f1598b65ae85e70f43d729d5b6563c0746445a0",
    "lighting-after": "803749010c5b2b89686188dd70f645e5f6486d970839bf9650a5abd4e5f5fb8a",
    "washer-drain-before": "3e6598f96d31aeedb558b439c6021101d39894acb11f2693612174d2422f4239",
    "washer-drain-after": "c53c6ac14a8a60b5d41ab6de6354b19afa806570a3f32a16025bcf0a6c7ac003",
    "sliding-door-roller-before": "a576ac9b83bcc1173d19b043496baf40f1756e64f57ca02655a58c750097f513",
    "sliding-door-roller-after": "776207437d3fc3319c8319040a5c77ee9abdbed81a937a0e4e3828f6461d1aa2",
    "sliding-door-track-before": "088ecaa204d1ba290181c1e9d6e9b5cd7bcbf5b85983819cc9494f8c7ca6c009",
    "sliding-door-track-after": "5ce459ff4c4fb0a5ba9898c4afdf30a39005aa432a4663c2ef7783b7716b2f7a",
    "hapjeong-faucet": "35db263799bd52f15736dd54c9c267b3b384fa89c788a7b2a528bfea24a653b4",
    "wallpaper-stain-day-1": "38202c920b0a57545ae1c67c41d0ec55704369af82710d44b97ce675b55072fc",
    "wallpaper-stain-day-3": "843e1601cd5bf67487412c028fbaf69e578575980e2a23ff17d27b95dcb208d9",
    "wallpaper-stain-day-4": "8eb507fe59e97882b331586187906eb286ed3c4f61badb89839f48467f11917e",
}


@dataclass(frozen=True)
class DemoWork:
    field: str
    name: str
    minutes: int
    symptom: str
    description: str
    photo_key: str
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
    photo_key: str
    visit_kind: str | None = None


WORKS = (
    DemoWork(
        "PLUMBING", "수전 교체", 60, "싱크대 수전 아래로 물이 샙니다.",
        "수전을 교체하고 연결부 누수 여부를 확인했습니다.",
        photo_key="faucet",
        confirmed_cause="수전 카트리지 및 연결 패킹 노후",
        parts=("싱크대 수전",),
    ),
    DemoWork(
        "DOORS_WINDOWS", "창문 잠금장치 교체", 45, "잠기지 않는 창문의 잠금장치가 걸리지 않습니다.",
        "잠기지 않는 창문의 잠금장치를 교체하고 창문 개폐 상태를 확인했습니다.",
        photo_key="window-lock",
        confirmed_cause="창문 잠금장치 파손",
        parts=("창문 잠금장치",),
    ),
    DemoWork(
        "WALLS_WALLPAPER", "벽지 보수", 90, "벽지 이음새가 들떠 있습니다.",
        "들뜬 구역을 보수하고 이음새를 정리했습니다.",
        photo_key="wallpaper-seam",
    ),
    DemoWork(
        "ELECTRICAL", "조명 교체", 45, "천장 조명이 간헐적으로 깜박입니다.",
        "조명을 교체하고 점등 상태를 확인했습니다.",
        photo_key="lighting",
    ),
    DemoWork(
        "APPLIANCES", "세탁기 배수 점검", 60, "세탁이 끝난 뒤 물이 남아 있습니다.",
        "배수 경로를 점검하고 배수 동작을 확인했습니다.",
        photo_key="washer-drain",
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
        photo_key="sliding-door-roller",
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
        photo_key="sliding-door-track",
        visit_kind="door_c_saturday",
    ),
)

BASE_TECH_LOGINS = tuple(
    f"demo-tech-{index:02}" for index in range(1, len(REGIONS) * len(WORKS) + 1)
)
DEMO_TECH_LOGINS = (*BASE_TECH_LOGINS, *(tech.login for tech in SCENARIO1_DOOR_TECHS))
DEMO_ACCOUNT_LOGINS = (*DEMO_TECH_LOGINS, *SCENARIO_USER_LOGINS)


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
    upgraded: bool = False
    schedules_extended: int = 0
    schedules_skipped: int = 0
    photos_updated: int = 0
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

    existing_guidance_ids = {row.id for row in ctx.references("GUIDANCE")}
    for entry in demo_guidance_entries(today):
        if entry["id"] not in existing_guidance_ids:
            entries.append(entry)

    insert_references(ctx.db, today, entries)
    return regions


def demo_guidance_source(key, title, today):
    return {
        "title": title,
        "reference": f"demo://fix-my-home/{key}",
        "version": SEED_VERSION,
        "verifiedAt": today.isoformat(),
        "usageBasis": "고쳐야집 시연용으로 직접 작성·검증한 모의 자가 점검 및 공식 AS 안내 자료",
        "verified": True,
    }


def demo_guidance_entries(today):
    return [
        reference_entry("guidance-self-help-sliding-door", "GUIDANCE", {
            "type": "SELF_HELP",
            "productType": "미닫이문",
            "requiredFields": ["productType"],
            "guides": [{
                "guideId": f"{SEED_VERSION}-guide-sliding-door",
                "source": demo_guidance_source("guide-sliding-door", "고쳐야집 모의 가이드 · 미닫이문 하단 레일 점검", today),
                "applicable": True,
                "conditions": [
                    "미닫이문이 닫힘 직전 바닥·레일에 가볍게 닿는 상태",
                    "유리 파손·프레임 뒤틀림·레일 이탈 위험이 없는 경우",
                ],
                "steps": [
                    "미닫이문을 완전히 열고 하단 레일 홈의 먼지·이물질을 브러시와 진공청소기로 제거하세요.",
                    "문 하단 측면의 롤러 높이 조절 나사 위치와 풀림 여부를 눈으로 확인하세요.",
                    "높이 조절 나사를 시계 방향으로 1/4바퀴씩 조금씩 돌려 문 하단과 바닥 사이 간격을 확인하세요.",
                    "문을 천천히 여닫으며 바닥 긁힘이 사라졌는지 확인하세요.",
                ],
                "supplies": ["십자드라이버", "마른 걸레·브러시", "진공청소기"],
                "warnings": ["문이 무거우므로 한 손으로 들어 올리거나 무리하게 레일에서 분리하지 마세요."],
                "prohibitions": ["레일을 망치로 두드리거나 바닥에 윤활유를 과도하게 뿌리지 마세요."],
                "stopConditions": ["롤러가 파손·이탈되었거나 나사를 조절해도 문이 계속 처지면 즉시 중단하고 문·창호 기사 점검을 받으세요."],
            }],
            "routes": [],
        }),
        reference_entry("guidance-self-help-faucet", "GUIDANCE", {
            "type": "SELF_HELP",
            "productType": "싱크대 수전",
            "requiredFields": ["productType"],
            "guides": [{
                "guideId": f"{SEED_VERSION}-guide-faucet",
                "source": demo_guidance_source("guide-faucet", "고쳐야집 모의 가이드 · 싱크대 수전 누수 1차 확인", today),
                "applicable": True,
                "conditions": [
                    "싱크대 하부 냉수·온수 앵글밸브를 손으로 잠글 수 있는 경우",
                    "배관 파열·분출이 아닌 연결부 미세 누수 초기 확인 단계",
                ],
                "steps": [
                    "싱크대 하부장 안쪽의 냉수·온수 앵글밸브를 시계 방향으로 끝까지 잠그세요.",
                    "수전 레버를 열어 배관 내부 잔압과 남은 물을 완전히 빼세요.",
                    "하부 연결 너트와 고무 패킹 부위의 물기를 마른 수건으로 닦고 풀림 여부를 확인하세요.",
                    "앵글밸브를 천천히 다시 열어 1분 이상 누수가 재발하는지 관찰하세요.",
                ],
                "supplies": ["마른 수건", "대야(잔수 받이용)", "몽키스패너"],
                "warnings": ["온수 밸브가 완전히 잠기지 않은 상태에서 너트를 풀면 화상·역류 위험이 있습니다."],
                "prohibitions": ["부식되어 굳은 앵글밸브를 무리하게 힘으로 돌리지 마세요."],
                "stopConditions": ["밸브를 잠가도 물이 계속 새거나 수전 몸체·카트리지 내부에서 누수되면 즉시 중단하고 배관 기사에게 교체 점검을 요청하세요."],
            }],
            "routes": [],
        }),
        reference_entry("guidance-self-help-wallpaper", "GUIDANCE", {
            "type": "SELF_HELP",
            "productType": "벽지",
            "requiredFields": ["productType"],
            "guides": [{
                "guideId": f"{SEED_VERSION}-guide-wallpaper",
                "source": demo_guidance_source("guide-wallpaper", "고쳐야집 모의 가이드 · 창가 벽지 물자국 경과 관찰", today),
                "applicable": True,
                "conditions": [
                    "창문 주변 벽지에 물자국·습기가 보이나 누전 위험이나 천장 붕괴 징후가 없는 초기 관찰 단계",
                ],
                "steps": [
                    "창틀 주변에 물기가 고여 있는지 마른 키친타월로 가볍게 눌러 습기 범위를 확인하세요.",
                    "비가 온 직후에는 제습기·선풍기로 실내 습도를 낮추고, 맑은 날 오전·저녁에 환기하세요.",
                    "첫날과 비슷한 거리·조명에서 날짜별 사진을 찍어 자국 경계 변화를 기록으로 남기세요.",
                ],
                "supplies": ["마른 수건·키친타월", "스마트폰(동일 구도 기록용)"],
                "warnings": ["벽면 콘센트·스위치 주변까지 젖어 있으면 감전 위험이 있으므로 만지지 마세요."],
                "prohibitions": ["내부 원인을 확인하기 전에 젖은 벽지 위에 시트지나 페인트를 덧바르지 마세요."],
                "stopConditions": ["자국이 아래쪽으로 계속 번지거나 벽면에서 물방울이 떨어지면 즉시 중단하고 누수·창틀 점검을 받으세요."],
            }],
            "routes": [],
        }),
        reference_entry("guidance-self-help-general", "GUIDANCE", {
            "type": "SELF_HELP",
            "requiredFields": [],
            "guides": [{
                "guideId": f"{SEED_VERSION}-guide-general",
                "source": demo_guidance_source("guide-general", "고쳐야집 모의 가이드 · 공통 안전 사전 점검", today),
                "applicable": True,
                "conditions": ["전기 합선·가스 냄새·대량 누수 등 긴급 위험 신호가 없는 일반 점검 상황"],
                "steps": [
                    "문제 부위 주변의 물기·이물질을 정리하고 안전한 거리에서 이상 부위를 확인하세요.",
                    "제품 측면·하단의 제품 종류·제조사 라벨을 입력하면 제품별 맞춤 점검 가이드와 공식 AS 경로를 볼 수 있어요.",
                    "분해나 부품 교체가 필요해 보이면 무리한 작업 대신 기사 상담으로 연결하세요.",
                ],
                "supplies": ["스마트폰(사진 기록용)", "마른 수건"],
                "warnings": ["전기·배관·고소 작업은 차단기·밸브 차단과 안전 장비 없이 직접 분해하지 마세요."],
                "prohibitions": ["전원이나 급수 밸브를 잠그지 않은 상태에서 배선·배관을 분리하지 마세요."],
                "stopConditions": ["타는 냄새·스파크·지속적인 물 분출이 확인되면 즉시 중단하고 긴급 조치를 우선하세요."],
            }],
            "routes": [],
        }),
        reference_entry("guidance-as-door", "GUIDANCE", {
            "type": "MANUFACTURER_AS",
            "manufacturer": "고쳐야집 모의 도어",
            "requiredFields": ["manufacturer"],
            "guides": [],
            "routes": [
                {
                    "label": "고쳐야집 모의 도어 공식 AS 접수 센터 (시연용)",
                    "contact": "https://demo.example.invalid/as/door",
                    "productSpecific": True,
                    "source": demo_guidance_source("as-door-web", "고쳐야집 모의 도어 고객지원", today),
                },
                {
                    "label": "고쳐야집 모의 도어 AS 고객센터 (시연용)",
                    "contact": "02-0000-1101",
                    "productSpecific": True,
                    "source": demo_guidance_source("as-door-tel", "고쳐야집 모의 도어 대표번호", today),
                },
            ],
        }),
        reference_entry("guidance-as-faucet", "GUIDANCE", {
            "type": "MANUFACTURER_AS",
            "manufacturer": "고쳐야집 모의 수전",
            "requiredFields": ["manufacturer"],
            "guides": [],
            "routes": [
                {
                    "label": "고쳐야집 모의 수전 공식 서비스센터 (시연용)",
                    "contact": "https://demo.example.invalid/as/faucet",
                    "productSpecific": True,
                    "source": demo_guidance_source("as-faucet-web", "고쳐야집 모의 수전 고객지원", today),
                },
                {
                    "label": "고쳐야집 모의 수전 부품·AS 상담전화 (시연용)",
                    "contact": "02-0000-1102",
                    "productSpecific": True,
                    "source": demo_guidance_source("as-faucet-tel", "고쳐야집 모의 수전 대표번호", today),
                },
            ],
        }),
        reference_entry("guidance-as-window", "GUIDANCE", {
            "type": "MANUFACTURER_AS",
            "manufacturer": "고쳐야집 모의 창호",
            "requiredFields": ["manufacturer"],
            "guides": [],
            "routes": [
                {
                    "label": "고쳐야집 모의 창호 공식 AS·실리콘 점검 안내 (시연용)",
                    "contact": "https://demo.example.invalid/as/window",
                    "productSpecific": True,
                    "source": demo_guidance_source("as-window-web", "고쳐야집 모의 창호 고객지원", today),
                },
                {
                    "label": "고쳐야집 모의 창호 고객센터 (시연용)",
                    "contact": "02-0000-1103",
                    "productSpecific": True,
                    "source": demo_guidance_source("as-window-tel", "고쳐야집 모의 창호 대표번호", today),
                },
            ],
        }),
        reference_entry("guidance-as-general", "GUIDANCE", {
            "type": "MANUFACTURER_AS",
            "requiredFields": [],
            "guides": [],
            "routes": [
                {
                    "label": "임대인·관리사무소 공식 시설 점검 안내 (일반 경로)",
                    "contact": "https://demo.example.invalid/as/general-support",
                    "productSpecific": False,
                    "source": demo_guidance_source("as-general", "고쳐야집 일반 공식 지원 안내", today),
                },
            ],
        }),
    ]


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


def seed_image(name):
    path = SEED_IMAGE_DIR / f"{name}.jpg"
    try:
        return path.read_bytes()
    except OSError as error:
        raise SeedError(f"시연용 이미지 파일을 읽을 수 없습니다. ({path})") from error


def portfolio_images(photo_key):
    return [seed_image(f"{photo_key}-{stage}") for stage in ("before", "after")]


def replace_seed_file(ctx, file, data, width, height):
    key = ctx.files.write(data)
    ctx.new_files.append(key)
    ctx.obsolete_files.append(file.key)
    file.key = key
    file.size = len(data)
    file.width = width
    file.height = height


def refresh_seed_delivery(ctx, request_id, replacements):
    quote = next((
        row for row in ctx.find("QUOTE", request_id=request_id)
        if row.data["terms"]["scope"] == SCENARIO3_QUOTE_SCOPE
    ), None)
    if not quote:
        return
    delivery = ctx.db.get(Resource, quote.data["contextDeliveryId"])
    if (
        not delivery or delivery.deleting or delivery.kind != "DELIVERY"
        or delivery.status != "READY" or delivery.data["reviewStatus"] != "CONFIRMED"
        or delivery.data["redactions"] or delivery.data.get("endedContent")
    ):
        return

    content = delivery.data["content"]
    updated = []
    for photo in content["photos"]:
        if photo["photoId"] not in replacements:
            updated.append(photo)
            continue
        old_jpeg, new_jpeg = replacements[photo["photoId"]]
        file = ctx.db.get(StoredFile, photo["media"]["mediaId"])
        if (
            file and file.resource_id == delivery.id
            and ctx.files.read(file.key) == mask_image(old_jpeg, [])[0]
        ):
            replace_seed_file(ctx, file, *mask_image(new_jpeg, []))
            photo = {**photo, "media": views.media(file)}
        updated.append(photo)
    if updated != content["photos"]:
        ctx.save(delivery, content={**content, "photos": updated})


def refresh_legacy_seed_photos(ctx, manifest):
    if manifest.data.get("photoSeedVersion", 0) >= PHOTO_SEED_VERSION:
        return 0

    portfolio_targets = {
        f"demo-tech-{index:02d}": (f"source-{work.field.lower()}", work.photo_key)
        for index, work in enumerate(WORKS, start=1)
    }
    portfolio_targets.update({tech.login: (tech.source_key, tech.photo_key) for tech in SCENARIO1_DOOR_TECHS})
    request_targets = {
        SCENARIO2_COMPETITOR_USER_LOGIN: ("hapjeong-faucet",),
        SCENARIO3_USER_LOGIN: tuple(f"wallpaper-stain-day-{day}" for day in (1, 3, 4)),
    }
    photos = ctx.db.execute(
        select(Resource, StoredFile, Account.login_id)
        .join(StoredFile, StoredFile.resource_id == Resource.id)
        .join(Account, Account.id == Resource.owner_id)
        .where(
            Account.login_id.in_(portfolio_targets.keys() | request_targets.keys()),
            Resource.kind.in_(("PORTFOLIO_PHOTO", "PHOTO")),
            Resource.deleting.is_(False),
            StoredFile.mime == "image/jpeg",
            StoredFile.width == 320,
            StoredFile.height == 240,
        )
    ).all()

    count, updated_cases, updated_requests = 0, {}, {}
    for photo, file, login in photos:
        source = None
        if photo.kind == "PORTFOLIO_PHOTO" and login in portfolio_targets:
            source_key, photo_key = portfolio_targets[login]
            source_id = f"{SEED_VERSION}-{source_key}"
            if photo.data["source"]["reference"] != source_id:
                continue
            source = ctx.db.get(ReferenceData, source_id)
            if not source or source.kind != "SOURCE" or source.version != SEED_VERSION or not source.verified:
                continue
            names = (f"{photo_key}-before", f"{photo_key}-after")
        elif photo.kind == "PHOTO" and login in request_targets:
            root = ctx.db.get(Resource, photo.request_id)
            if not root or root.deleting:
                continue
            names = request_targets[login]
        else:
            continue

        old_jpeg = ctx.files.read(file.key)
        digest = hashlib.sha256(old_jpeg).hexdigest()
        name = next((name for name in names if LEGACY_PHOTO_SHA256[name] == digest), None)
        if not name:
            continue
        raw = seed_image(name)
        data, width, height, _ = normalize_image(raw)
        replace_seed_file(ctx, file, data, width, height)
        count += 1

        if source:
            asset_hashes = [*source.data["assetSha256"], hashlib.sha256(raw).hexdigest()]
            source.data = {
                **source.data,
                "usageBasis": SEED_PHOTO_USAGE,
                "assetSha256": list(dict.fromkeys(asset_hashes)),
            }
            ctx.save(photo, source={**photo.data["source"], "usageBasis": SEED_PHOTO_USAGE})
            updated_cases.setdefault(source.id, set()).add(file.id)
        else:
            ctx.save(photo)
            updated_requests.setdefault(photo.request_id, {})[photo.id] = (old_jpeg, data)

    if updated_cases:
        for row in ctx.find("CASE"):
            case = row.data["case"]
            source = case["source"]
            media_ids = [*case["beforeMediaIds"], *case["afterMediaIds"]]
            if updated_cases.get(source["reference"], set()).intersection(media_ids):
                ctx.save(row, case={**case, "source": {**source, "usageBasis": SEED_PHOTO_USAGE}})
    for request_id, replacements in updated_requests.items():
        refresh_seed_delivery(ctx, request_id, replacements)

    if ctx.obsolete_files:
        cleanup = ctx.create("FILE_CLEANUP", {"error": None}, status="QUEUED")
        ctx.enqueue(cleanup, "DELETE", {
            "resourceIds": [], "fileKeys": ctx.obsolete_files, "photoCount": 0,
        })
    manifest.data = {**manifest.data, "photoSeedVersion": PHOTO_SEED_VERSION}
    return count


def register_case_portfolio(
    ctx, tech, today, *, source_key, source_title, title, field_name, symptom,
    confirmed_cause, description, parts, images,
):
    source = {
        "title": source_title,
        "reference": f"{SEED_VERSION}-{source_key}",
        "version": SEED_VERSION,
        "verifiedAt": today.isoformat(),
        "usageBasis": SEED_PHOTO_USAGE,
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


def add_portfolio(ctx, tech, work, today):
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
        images=portfolio_images(work.photo_key),
    )


def create_demo_account(ctx, login_id, roles):
    return create_account(ctx.db, ctx.settings, login_id, DEMO_PASSWORD, roles, min_password_length=1)


def create_scenario_door_technicians(ctx, yeonnam, today, through):
    schedules, tech_by_login = [], {}
    for item in SCENARIO1_DOOR_TECHS:
        existing_account = ctx.db.scalar(select(Account).where(Account.login_id == item.login))
        if existing_account:
            tech = ctx.db.scalar(select(Resource).where(
                Resource.kind == "TECHNICIAN", Resource.owner_id == existing_account.id,
            ))
            tech_by_login[item.login] = (existing_account, tech)
            continue
        account = create_demo_account(ctx, item.login, ["USER", "TECHNICIAN"])
        tech = ctx.db.scalar(select(Resource).where(
            Resource.kind == "TECHNICIAN", Resource.owner_id == account.id,
        ))
        owner = Context(
            ctx.db, Actor(account.id, "TECHNICIAN", tech.id, None), ctx.settings,
            new_files=ctx.new_files,
        )
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
            images=portfolio_images(item.photo_key),
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


def create_technicians(ctx, regions, today, through):
    by_key = {region.key: region for region in regions}
    collision = ctx.db.scalar(
        select(Account.login_id).where(Account.login_id.in_(DEMO_TECH_LOGINS)).limit(1)
    )
    if collision:
        raise SeedError(f"기사 로그인 ID {collision}이(가) 이미 사용 중입니다.")

    schedules, tech_by_login = [], {}
    for index, login in enumerate(BASE_TECH_LOGINS):
        region_index, work_index = divmod(index, len(WORKS))
        region, work = regions[region_index], WORKS[work_index]
        account = create_demo_account(ctx, login, ["USER", "TECHNICIAN"])
        tech = ctx.db.scalar(select(Resource).where(
            Resource.kind == "TECHNICIAN", Resource.owner_id == account.id,
        ))
        owner = Context(
            ctx.db, Actor(account.id, "TECHNICIAN", tech.id, None), ctx.settings,
            new_files=ctx.new_files,
        )
        media_ids = add_portfolio(owner, tech, work, today) if region_index == 0 else []
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

    door_schedules, door_techs = create_scenario_door_technicians(ctx, by_key["yeonnam"], today, through)
    schedules.extend(door_schedules)
    tech_by_login.update(door_techs)
    return schedules, tech_by_login


def ensure_scenario_starter_users(ctx):
    for login in (SCENARIO1_USER_LOGIN, SCENARIO2_USER_LOGIN):
        if not ctx.db.scalar(select(Account).where(Account.login_id == login)):
            create_demo_account(ctx, login, ["USER"])


def seed_scenario_requests(ctx, regions, today, through, tech_by_login):
    collision = ctx.db.scalar(
        select(Account.login_id).where(Account.login_id.in_(SCENARIO_USER_LOGINS)).limit(1)
    )
    if collision:
        raise SeedError(f"시연 사용자 로그인 ID {collision}이(가) 이미 사용 중입니다.")

    ensure_scenario_starter_users(ctx)
    by_key = {region.key: region for region in regions}

    # 시나리오 2 비교용: 합정동 수전 교체 요청 (목요일 14:00~17:00, 동선 제안 탐색 활성)
    hapjeong_account = create_demo_account(ctx, SCENARIO2_COMPETITOR_USER_LOGIN, ["USER"])
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
        [{"bytes": seed_image("hapjeong-faucet")}],
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
    seoyeon_account = create_demo_account(ctx, SCENARIO3_USER_LOGIN, ["USER"])
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
            {"bytes": seed_image("wallpaper-stain-day-1")},
            {"bytes": seed_image("wallpaper-stain-day-3")},
            {"bytes": seed_image("wallpaper-stain-day-4")},
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
            "product": {
                "productType": "벽지",
                "manufacturer": "고쳐야집 모의 창호",
                "modelName": "WIN-240",
            },
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
            "scope": SCENARIO3_QUOTE_SCOPE,
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


def upgrade_existing_seed(ctx, manifest, today, through):
    regions = prepare_references(ctx, today)
    by_key = {region.key: region for region in regions}
    last_day = date.fromisoformat(manifest.data["availableThrough"])
    effective_through = max(last_day, through)
    extended_result = extend_schedules(ctx, manifest, today, effective_through)
    schedules = list(manifest.data["schedules"])

    # 기존 demo-tech-01에 합정동 활동 지역과 목요일 동선 시연 외부 방문 일정을 보강한다.
    route_account = ctx.db.scalar(select(Account).where(Account.login_id == DEMO_LOGIN))
    if route_account:
        route_tech = ctx.db.scalar(select(Resource).where(
            Resource.kind == "TECHNICIAN", Resource.owner_id == route_account.id,
        ))
        if route_tech:
            route_ctx = Context(
                ctx.db, Actor(route_account.id, "TECHNICIAN", route_tech.id, None), ctx.settings,
                new_files=ctx.new_files,
            )
            profile = dict(route_tech.data["profile"])
            if by_key["hapjeong"].id not in profile["regionIds"]:
                profile = {**profile, "regionIds": [*profile["regionIds"], by_key["hapjeong"].id]}
                technicians.profile(route_ctx, route_tech, {
                    "expectedRevision": str(route_tech.revision),
                    "profile": profile,
                })
            route_schedule = ctx.db.scalar(select(Resource).where(
                Resource.kind == "SCHEDULE", Resource.technician_id == route_tech.id,
            ))
            if route_schedule:
                locations = {"yeonnam": by_key["yeonnam"].location, "seogyo": by_key["seogyo"].location}
                existing_ids = {v.get("externalVisitId") for v in route_schedule.data.get("externalVisits", [])}
                extra_visits = [
                    v for v in scenario_external_visits("route_thursday", locations, today, effective_through)
                    if v["externalVisitId"] not in existing_ids
                ]
                was_revision = route_schedule.revision
                if extra_visits:
                    ctx.save(
                        route_schedule,
                        externalVisits=[*route_schedule.data.get("externalVisits", []), *extra_visits],
                    )
                for idx, entry in enumerate(schedules):
                    if entry["id"] == route_schedule.id:
                        schedules[idx] = {
                            **entry,
                            "revision": route_schedule.revision if entry["revision"] == was_revision else entry["revision"],
                            "shiftIndex": entry.get("shiftIndex", 0),
                            "visitKind": "route_thursday",
                            "locations": locations,
                        }
                        break

    door_schedules, _ = create_scenario_door_technicians(
        ctx, by_key["yeonnam"], today, effective_through,
    )
    schedules.extend(door_schedules)

    wall_account = ctx.db.scalar(select(Account).where(Account.login_id == SCENARIO3_TECH_LOGIN))
    wall_tech = ctx.db.scalar(select(Resource).where(
        Resource.kind == "TECHNICIAN", Resource.owner_id == wall_account.id,
    )) if wall_account else None
    if wall_account and wall_tech and not ctx.db.scalar(
        select(Account).where(Account.login_id.in_([SCENARIO2_COMPETITOR_USER_LOGIN, SCENARIO3_USER_LOGIN])).limit(1)
    ):
        seed_scenario_requests(
            ctx, regions, today, effective_through,
            {SCENARIO3_TECH_LOGIN: (wall_account, wall_tech)},
        )
    else:
        ensure_scenario_starter_users(ctx)
        seoyeon_account = ctx.db.scalar(select(Account).where(Account.login_id == SCENARIO3_USER_LOGIN))
        if seoyeon_account:
            seoyeon_item = ctx.db.scalar(select(Resource).where(
                Resource.kind == "WORK_ITEM", Resource.owner_id == seoyeon_account.id,
            ))
            if seoyeon_item and not (seoyeon_item.data.get("facts", {}).get("product") or {}).get("manufacturer"):
                updated_facts = dict(seoyeon_item.data["facts"])
                updated_facts["product"] = {
                    "productType": "벽지",
                    "manufacturer": "고쳐야집 모의 창호",
                    "modelName": "WIN-240",
                }
                seoyeon_item.data = {**seoyeon_item.data, "facts": updated_facts}

    manifest.data = {
        **manifest.data,
        "availableThrough": effective_through.isoformat(),
        "schedules": schedules,
        "scenariosSeeded": True,
        "scenarioSeedVersion": SCENARIO_SEED_VERSION,
    }
    return SeedResult(
        effective_through,
        upgraded=True,
        schedules_extended=extended_result.schedules_extended,
        schedules_skipped=extended_result.schedules_skipped,
        scenario_thursday=next_weekday(today, THURSDAY),
        scenario_saturday=next_weekday(today, SATURDAY),
    )


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
    manifest.data = {
        **manifest.data,
        "availableThrough": through.isoformat(),
        "schedules": schedules,
    }
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
                if manifest.data.get("scenarioSeedVersion", 0) < SCENARIO_SEED_VERSION:
                    result = upgrade_existing_seed(ctx, manifest, today, through)
                else:
                    result = extend_schedules(ctx, manifest, today, through)
                photos_updated = refresh_legacy_seed_photos(ctx, manifest)
                accounts = db.scalars(select(Account).where(Account.login_id.in_(DEMO_ACCOUNT_LOGINS)))
                for account in accounts:
                    if not verify_password(DEMO_PASSWORD, account.password_hash):
                        account.password_hash = hash_password(DEMO_PASSWORD)
                return replace(result, photos_updated=photos_updated, generated_password=DEMO_PASSWORD)

            regions = prepare_references(ctx, today)
            schedules, tech_by_login = create_technicians(ctx, regions, today, through)
            seed_scenario_requests(ctx, regions, today, through, tech_by_login)
            db.add(ReferenceData(
                id=SEED_VERSION,
                kind=SEED_KIND,
                version=SEED_VERSION,
                verified=False,
                data={
                    "availableThrough": through.isoformat(),
                    "schedules": schedules,
                    "scenariosSeeded": True,
                    "scenarioSeedVersion": SCENARIO_SEED_VERSION,
                    "photoSeedVersion": PHOTO_SEED_VERSION,
                },
            ))
            return SeedResult(
                through,
                created=True,
                scenario_thursday=next_weekday(today, THURSDAY),
                scenario_saturday=next_weekday(today, SATURDAY),
                generated_password=DEMO_PASSWORD,
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
    elif result.upgraded:
        print("기존 초기 시연 DB에 대표 시연 시나리오 3종 데이터를 보강했습니다.")
    elif result.schedules_extended or result.schedules_skipped:
        print(f"기사 일정 {result.schedules_extended}건을 연장했습니다.")
        if result.schedules_skipped:
            print(f"적재 후 변경된 일정 {result.schedules_skipped}건은 연장 대상에서 제외했습니다.")
    elif not result.photos_updated:
        print("오늘 기준 초기 시연 데이터가 준비되어 있습니다.")
    if result.photos_updated:
        print(f"기존 시연 사진 {result.photos_updated}장을 새 사진으로 교체했습니다.")
    print(f"시연 일정은 {result.available_through}까지입니다. (한국 시간)")
    if result.scenario_saturday:
        print(
            f"시나리오 1 기준 토요일: {result.scenario_saturday} "
            f"(사용자 민서 {SCENARIO1_USER_LOGIN}, 기사 A {SCENARIO1_TECH_A_LOGIN}, B {SCENARIO1_TECH_B_LOGIN}, C {SCENARIO1_TECH_C_LOGIN})"
        )
    if result.scenario_thursday:
        print(
            f"시나리오 2 기준 목요일: {result.scenario_thursday} "
            f"(사용자 지훈 {SCENARIO2_USER_LOGIN}, 기사-2 {DEMO_LOGIN}, 비교 요청 {SCENARIO2_COMPETITOR_USER_LOGIN})"
        )
    print(f"시나리오 3 계정: 임차인 서연 {SCENARIO3_USER_LOGIN}, 기사-3 {SCENARIO3_TECH_LOGIN}")
    print(f"공용 시연 비밀번호 {result.generated_password}")


if __name__ == "__main__":
    main()
