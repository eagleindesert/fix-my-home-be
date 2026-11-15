"""E2E 전용 계정·기준 자료를 추가하고 Bash 실행 설정을 만든다."""

import argparse
import hashlib
import json
import secrets
from pathlib import Path
from tempfile import NamedTemporaryFile

from PIL import Image, ImageDraw
from sqlalchemy import select

from app.admin import create_account
from app.config import get_settings
from app.db import Job, ReferenceData, Resource, session_factory
from app.errors import DomainError
from app.schema import validate_schema
from app.security import Actor
from app.services import deletion, requests
from app.services.context import Context


def write_json(path, value):
    # 서버 준비를 기다리는 Bash가 작성 중인 설정을 읽지 않도록 원자적으로 교체한다.
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            json.dump(value, file, ensure_ascii=False, indent=2)
            file.write("\n")
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def prepare(settings, factory, directory, base_url):
    """기존 자료를 덮어쓰지 않고 매번 독립된 테스트 자료를 추가한다."""
    if settings.environment == "production":
        raise ValueError("E2E 자료는 development/test 전용 DB에만 준비할 수 있습니다.")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (directory / "config.json").exists():
        raise ValueError("config.json이 이미 있습니다. 새 출력 디렉터리를 지정하세요.")

    prefix = "e2e-" + secrets.token_hex(6)
    region_id, location_id = f"{prefix}-region", f"{prefix}-location"
    region = {
        "city": "서울특별시", "district": "E2E테스트구",
        "neighborhood": "E2E테스트동", "regionId": region_id,
    }
    photo = directory / "photo.png"
    Image.new("RGB", (80, 60), (220, 80, 40)).save(photo)
    wall_photos = {}
    for name, bounds, color in (
        ("before", (24, 20, 40, 34), (174, 151, 113)),
        ("after", (18, 15, 49, 42), (147, 120, 91)),
        ("unchanged", (24, 20, 40, 34), (174, 151, 113)),
        ("incomparable", (4, 5, 34, 48), (113, 102, 81)),
    ):
        wall = Image.new("RGB", (80, 60), (238, 235, 221))
        ImageDraw.Draw(wall).ellipse(bounds, fill=color)
        path = directory / f"wall-{name}.png"
        wall.save(path)
        wall_photos[name] = str(path.resolve())
    source = {
        "title": "E2E 합성 자료", "reference": prefix, "version": prefix,
        "usageBasis": "직접 생성한 단색 이미지와 가상 수리 사례",
    }
    case = {
        "title": "E2E 수전 점검", "fields": ["PLUMBING"],
        "initialSymptom": "가상 수전 누수", "confirmedCause": None,
        "workDescription": "가상 연결부 점검", "parts": [],
        "beforeMediaIds": [], "afterMediaIds": [], "dataType": "MOCK", "source": source,
    }
    updated_case = {**case, "workDescription": "가상 연결부 점검 및 상태 기록"}

    def case_hash(value):
        content = {key: item for key, item in value.items() if key != "source"}
        encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()

    accounts = {}
    with factory() as db, db.begin():
        validate_schema(db.connection())
        for name, roles in (
            ("user", ["USER"]), ("other", ["USER"]),
            ("technician", ["USER", "TECHNICIAN"]),
            ("noCaseTechnician", ["USER", "TECHNICIAN"]),
        ):
            credentials = {"loginId": f"{prefix}-{name}", "password": secrets.token_urlsafe(24)}
            account = create_account(db, settings, credentials["loginId"], credentials["password"], roles)
            accounts[name] = credentials
            if name == "user":
                owner_id = account.id
            if "TECHNICIAN" in roles:
                technician = db.scalar(select(Resource).where(
                    Resource.kind == "TECHNICIAN", Resource.owner_id == account.id,
                ))
                ctx = Context(db, Actor(account.id, "TECHNICIAN", technician.id, None), settings)
                ctx.create("SCHEDULE", {
                    "availability": [], "externalVisits": [],
                    "departureLocationId": location_id, "returnLocationId": location_id,
                }, technician_id=technician.id)

        references = [
            (region_id, "REGION", {
                key: value for key, value in region.items() if key != "regionId"
            } | {"representativeLocationId": location_id}),
            (f"{prefix}-travel", "TRAVEL", {
                "fromLocationId": location_id, "toLocationId": location_id, "minutes": 15,
            }),
            (f"{prefix}-duration", "DURATION", {
                "workType": f"{prefix} 수전 교체", "quantity": 1, "minutes": 60,
            }),
            (f"{prefix}-source", "SOURCE", {
                **source, "identifiersRemoved": True,
                "assetSha256": [hashlib.sha256(photo.read_bytes()).hexdigest()],
                "caseSha256": [case_hash(case), case_hash(updated_case)],
            }),
        ]
        # 예약 동선은 서로 다른 인근 동 사이의 고정 모의 이동시간으로 검사한다.
        neighbors = {name: f"{prefix}-{name}-location" for name in ("before", "after")}
        for name, neighbor in neighbors.items():
            references.append((f"{prefix}-{name}-region", "REGION", {
                "city": "서울특별시", "district": "E2E테스트구",
                "neighborhood": f"E2E{name}동", "representativeLocationId": neighbor,
            }))
        locations = [location_id, *neighbors.values()]
        for start in locations:
            for end in locations:
                if start == end == location_id:
                    continue
                minutes = 10 if start in neighbors.values() and end in neighbors.values() else 5
                references.append((f"{prefix}-travel-{locations.index(start)}-{locations.index(end)}", "TRAVEL", {
                    "fromLocationId": start, "toLocationId": end, "minutes": minutes,
                }))
        guidance_source = {
            "title": "E2E 모의 지원 안내", "reference": prefix, "version": prefix,
            "verifiedAt": "2026-01-01", "verified": True,
            "usageBasis": "테스트 전용 가상 절차 및 example.invalid 주소; 실제 수리 안내가 아님",
        }
        guide_id = f"{prefix}-self-help"
        guide = {
            "guideId": guide_id, "source": guidance_source, "applicable": True,
            "conditions": ["E2E 모의 점검 대상"], "steps": ["가상 상태 표시를 확인한다."],
            "supplies": [], "warnings": ["실제 기기를 조작하지 않는다."],
            "prohibitions": ["실제 설비 분해 금지"], "stopConditions": ["실제 위험 징후가 있으면 중단한다."],
        }
        manufacturer = f"E2E-{prefix}"
        official_url = f"https://example.invalid/{prefix}/manufacturer"
        emergency_url = f"https://example.invalid/{prefix}/emergency"
        references.extend([
            (guide_id, "GUIDANCE", {"type": "SELF_HELP", "guides": [guide], "routes": []}),
            (f"{prefix}-manufacturer", "GUIDANCE", {
                "type": "MANUFACTURER_AS", "manufacturer": manufacturer,
                "requiredFields": ["manufacturer"], "guides": [], "routes": [{
                    "label": "E2E 가상 제조사 지원", "contact": official_url,
                    "productSpecific": True, "source": guidance_source,
                }],
            }),
            (f"{prefix}-emergency", "GUIDANCE", {
                "type": "EMERGENCY", "guides": [guide], "routes": [{
                    "label": "E2E 가상 긴급 대안", "contact": emergency_url,
                    "productSpecific": False, "source": guidance_source,
                }],
            }),
        ])
        for reference_id, kind, data in references:
            db.add(ReferenceData(
                id=reference_id, kind=kind, version=prefix, verified=True, data=data,
            ))

        # 재시도 API의 선행 조건: 이전 실행에서 저장소 정리에 실패한 삭제 작업.
        # 이후 실행 중에는 DB를 만지지 않고 HTTP로 재시도와 실제 파일 삭제를 확인한다.
        ctx = Context(db, Actor(owner_id, "USER", None, None), settings)
        root = requests.create_request(ctx, {
            "symptom": "E2E 삭제 재시도용 가상 자료", "region": region,
            "photos": [{"dateConfirmed": False}],
        }, [{"bytes": photo.read_bytes()}])
        pending = deletion.create(ctx, {
            "targetType": "REQUEST", "targetId": root.id, "includeAllReferences": True,
        })
        pending.status = "FAILED"
        pending.data = {
            **pending.data,
            "error": DomainError("PROCESSING_FAILED", "E2E 재시도 선행 조건", retryable=True).body(),
        }
        db.get(Job, pending.id).state = "DONE"
        failed_job_id = pending.id

    config = {
        "baseUrl": base_url.rstrip("/"), "origin": settings.public_origin,
        "accounts": accounts, "region": region, "locationId": location_id,
        "workType": f"{prefix} 수전 교체", "photoPath": str(photo.resolve()),
        "source": source, "case": case, "updatedCase": updated_case,
        "wallPhotos": wall_photos,
        "neighborLocations": neighbors,
        "emptyRegionId": f"{prefix}-before-region",
        "guidance": {"guideId": guide_id, "manufacturer": manufacturer,
                     "officialUrl": official_url, "emergencyUrl": emergency_url},
        "failedDeletionJobId": failed_job_id,
        "ai": {"expectedStatus": "SUCCEEDED", "expectedErrorCode": None},
    }
    write_json(directory / "config.json", config)
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", required=True, help="/v1까지 포함한 테스트 서버 주소")
    args = parser.parse_args()
    settings = get_settings()
    prepare(settings, session_factory(), args.output.resolve(), args.base_url)
    print(f"설정 파일: {args.output.resolve() / 'config.json'}")


if __name__ == "__main__":
    main()
