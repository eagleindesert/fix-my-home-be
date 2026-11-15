"""E2E 전용 계정·기준 자료를 추가하고 Bash 실행 설정을 만든다."""

import argparse
import hashlib
import json
import secrets
from pathlib import Path
from tempfile import NamedTemporaryFile

from PIL import Image
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
        ):
            credentials = {"loginId": f"{prefix}-{name}", "password": secrets.token_urlsafe(24)}
            account = create_account(db, settings, credentials["loginId"], credentials["password"], roles)
            accounts[name] = credentials
            if name == "user":
                owner_id = account.id
            if name == "technician":
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
