"""실행 중인 Compose의 be 컨테이너에서만 사용하는 E2E 준비·정리 도구.

애플리케이션과 같은 PostgreSQL 및 파일 저장소를 사용한다. HTTP 시나리오에
필요한 운영자 발급 계정·검증 자료만 준비하고, API와 worker는 실행하지 않는다.
stdout의 준비 결과에는 임시 비밀번호가 있으므로 셸에서 비공개 파일로 받는다.
"""

import argparse
import base64
import copy
import hashlib
import io
import json
import re
import secrets
import sys
import time

from PIL import Image
from sqlalchemy import delete, or_, select, text

from app.config import get_settings
from app.db import Account, Job, ReferenceData, Resource, StoredFile, engine, lock, now, session_factory
from app.errors import DomainError
from app.media import FileStore
from app.schema import validate_schema
from app.security import Actor
from app.services.accounts import create_account
from app.services.context import Context


FIXTURE_VERSION = 1
RUN_ID_PATTERN = re.compile(r"e2e-[a-f0-9]{32}")
ACCOUNT_NAMES = ("user", "other", "technician")
REFERENCE_NAMES = (
    "region", "travel", "duration", "source", "self-help", "manufacturer-as",
    "emergency-trigger", "emergency-guide",
)


class FixtureError(RuntimeError):
    """접속 정보나 SQL 매개변수를 포함하지 않는 사용자용 오류."""


def validate_run_id(run_id):
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise FixtureError("run ID는 e2e- 뒤에 소문자 16진수 32자리여야 합니다.")


def validate_environment(settings, connection):
    if settings.environment not in ("development", "test"):
        raise FixtureError("E2E 준비·정리는 development/test 환경에서만 허용합니다.")
    if connection.dialect.name != "postgresql":
        raise FixtureError("Compose E2E에는 실제 PostgreSQL이 필요합니다.")
    # docker exec 클라이언트 종료 후에도 DB 잠금 대기가 무한히 남지 않도록 제한한다.
    connection.execute(text("SET LOCAL lock_timeout = '10s'"))
    connection.execute(text("SET LOCAL statement_timeout = '30s'"))
    version = int(connection.scalar(text("SHOW server_version_num")))
    if not 170000 <= version < 180000:
        raise FixtureError("docker-compose.yaml과 같은 PostgreSQL 17이 필요합니다.")
    try:
        validate_schema(connection)
    except RuntimeError as error:
        raise FixtureError("실행 이미지와 PostgreSQL 스키마가 일치하지 않습니다.") from error


def check(settings, factory, run_id):
    """be/worker의 실제 설정과 스키마를 쓰기 작업 없이 비교할 정보."""
    validate_run_id(run_id)
    with factory() as db:
        validate_environment(settings, db.connection())
        # inet의 ::text 변환은 /32 등을 붙이므로 Docker와 비교할 호스트 주소만 조회한다.
        database_address = db.scalar(text("SELECT host(inet_server_addr())"))
    ai_configured = bool(settings.openai_api_key.get_secret_value() and settings.openai_model)
    ai_config = {
        "key": settings.openai_api_key.get_secret_value(),
        "model": settings.openai_model,
        "baseUrl": settings.openai_base_url.strip(),
    }
    return {
        "environment": settings.environment,
        "databaseFingerprint": hashlib.sha256(
            settings.database_url.get_secret_value().encode(),
        ).hexdigest(),
        "databaseServerAddress": database_address,
        "publicOrigin": settings.public_origin,
        "rootPath": settings.root_path,
        "storageDir": str(settings.storage_dir),
        "aiConfigFingerprint": hashlib.sha256(
            json.dumps(ai_config, sort_keys=True, separators=(",", ":")).encode(),
        ).hexdigest(),
        "aiExpectedStatus": "SUCCEEDED" if ai_configured else "FAILED",
    }


def case_digest(value):
    content = {key: item for key, item in value.items() if key != "source"}
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def synthetic_content(run_id):
    """실제 접수 사진·연락처가 없는 합성 이미지와 검증 대상 사례."""
    buffer = io.BytesIO()
    Image.new("RGB", (80, 60), color=(80, 130, 160)).save(buffer, format="PNG")
    photo = buffer.getvalue()
    source = {
        "title": "E2E 직접 생성 합성 자료",
        "reference": run_id,
        "version": run_id,
        "verifiedAt": now().date().isoformat(),
        "usageBasis": "E2E 전용으로 직접 만든 이미지와 모의 사례. 실제 접수 자료 아님.",
    }
    case = {
        "title": "E2E 모의 수전 교체",
        "fields": ["PLUMBING"],
        "initialSymptom": "합성 사진을 사용한 모의 물방울 증상",
        "confirmedCause": None,
        "workDescription": "E2E용 모의 점검과 수전 교체 기록",
        "parts": [],
        "beforeMediaIds": [],
        "afterMediaIds": [],
        "dataType": "MOCK",
        "source": source,
    }
    updated_case = copy.deepcopy(case)
    updated_case["workDescription"] = "E2E용 모의 점검과 수전 교체 기록 정정"
    return photo, source, case, updated_case


def reference_rows(run_id, source, photo, case, updated_case):
    region = {
        "city": "서울특별시",
        "district": "E2E모의구",
        "neighborhood": run_id + "동",
    }
    location_id = run_id + "-location"
    work_type = run_id + "-수전 교체"
    product = {
        "productType": run_id + "-제품",
        "manufacturer": run_id + "-제조사",
        "modelName": run_id + "-모델",
    }
    verified_source = {**source, "verified": True}
    guide_id = run_id + "-guide"
    trigger_id = run_id + "-emergency-trigger"
    guide = {
        "guideId": guide_id,
        "source": verified_source,
        "applicable": True,
        "conditions": ["직접 생성한 E2E 모의 제품에만 적용"],
        "steps": ["E2E 모의 기록을 확인하세요."],
        "supplies": [],
        "warnings": ["실제 수리 안내가 아닌 E2E 검증용 자료입니다."],
        "prohibitions": ["이 모의 안내를 실제 제품에 적용하지 마세요."],
        "stopConditions": ["실제 제품이면 모의 안내 사용을 중단하세요."],
    }
    values = {
        "region": ("REGION", {**region, "representativeLocationId": location_id}),
        "travel": ("TRAVEL", {
            "fromLocationId": location_id, "toLocationId": location_id, "minutes": 15,
        }),
        "duration": ("DURATION", {"workType": work_type, "quantity": 1, "minutes": 60}),
        "source": ("SOURCE", {
            **source,
            "identifiersRemoved": True,
            "assetSha256": [hashlib.sha256(photo).hexdigest()],
            "caseSha256": [case_digest(case), case_digest(updated_case)],
        }),
        "self-help": ("GUIDANCE", {
            "type": "SELF_HELP", **product, "requiredFields": list(product),
            "guides": [guide], "routes": [],
        }),
        "manufacturer-as": ("GUIDANCE", {
            "type": "MANUFACTURER_AS", **product, "requiredFields": list(product),
            "guides": [],
            "routes": [{
                "label": "E2E 모의 제조사 경로", "contact": "https://e2e.invalid/support",
                "productSpecific": True, "source": verified_source,
            }],
        }),
        "emergency-trigger": ("EMERGENCY_TRIGGER", {"label": "E2E 모의 긴급 확인"}),
        "emergency-guide": ("GUIDANCE", {
            "type": "EMERGENCY", "triggerId": trigger_id,
            "guides": [{**guide, "guideId": run_id + "-emergency-guide"}], "routes": [],
        }),
    }
    rows = [ReferenceData(
        id=f"{run_id}-{name}", kind=kind, version=run_id, verified=True,
        data={**data, "provenance": {
            "source": "E2E 직접 생성 모의 자료", "reviewedBy": run_id,
            "reviewedAt": source["verifiedAt"],
        }},
    ) for name, (kind, data) in values.items()]
    return rows, {
        "region": {**region, "regionId": run_id + "-region", "version": run_id},
        "locationId": location_id,
        "workType": work_type,
        "product": product,
        "guideId": guide_id,
        "emergencyTriggerId": trigger_id,
    }


def prepare(settings, factory, run_id):
    validate_run_id(run_id)
    photo, source, case, updated_case = synthetic_content(run_id)
    references, config = reference_rows(run_id, source, photo, case, updated_case)
    accounts = {}
    with factory() as db, db.begin():
        validate_environment(settings, db.connection())
        lock(db, "e2e-prepare", run_id)
        if (db.scalar(select(Account.id).where(Account.login_id.startswith(run_id)))
                or db.scalar(select(ReferenceData.id).where(ReferenceData.id.startswith(run_id)))):
            raise FixtureError("이미 사용 중인 E2E run ID입니다. 새 run ID로 실행하세요.")
        db.add_all(references)
        for name in ACCOUNT_NAMES:
            password = secrets.token_urlsafe(24)
            roles = ["USER", "TECHNICIAN"] if name == "technician" else ["USER"]
            account = create_account(db, settings, f"{run_id}-{name}", password, roles)
            accounts[name] = {
                "accountId": account.id, "loginId": account.login_id, "password": password,
            }

        technician_account = accounts["technician"]["accountId"]
        technician = db.scalar(select(Resource).where(
            Resource.kind == "TECHNICIAN", Resource.owner_id == technician_account,
        ))
        ctx = Context(db, Actor(technician_account, "TECHNICIAN", technician.id, None), settings)
        ctx.create("SCHEDULE", {
            "availability": [], "externalVisits": [],
            "departureLocationId": config["locationId"], "returnLocationId": config["locationId"],
        }, technician_id=technician.id)

        # 재시도 API의 입력 상태만 준비한다. 재시도 이후 삭제는 실제 worker가 처리한다.
        user_ctx = Context(db, Actor(accounts["user"]["accountId"], "USER", None, None), settings)
        deleted_target = user_ctx.create("REQUEST", {"e2eRunId": run_id}, status="OPEN", deleting=True)
        failed_job = user_ctx.create("DELETION_JOB", {
            "targetType": "REQUEST", "targetId": deleted_target.id,
            "affectedWorkItemIds": [], "affectedResourceIds": [deleted_target.id],
            "accessBlocked": True, "restoredPhotoSlots": 0,
            "error": DomainError(
                "PROCESSING_FAILED", "E2E 재시도용 사전 실패 상태", retryable=True,
            ).body(),
        }, status="FAILED")
        db.add(Job(id=failed_job.id, kind="DELETE", state="DONE", payload={
            "resourceIds": [deleted_target.id], "fileKeys": [], "photoCount": 0,
        }))
        db.add(ReferenceData(
            id=run_id + "-manifest", kind="E2E_RUN", version=run_id, verified=False,
            data={
                "fixtureVersion": FIXTURE_VERSION,
                "runId": run_id,
                "accounts": {name: {
                    "accountId": value["accountId"], "loginId": value["loginId"],
                } for name, value in accounts.items()},
                "signupLoginId": run_id + "-signup",
                "referenceIds": [row.id for row in references],
            },
        ))

    ai_configured = bool(settings.openai_api_key.get_secret_value() and settings.openai_model)
    return {
        "runId": run_id,
        "accounts": accounts,
        **config,
        "source": source,
        "case": case,
        "updatedCase": updated_case,
        "photoBase64": base64.b64encode(photo).decode("ascii"),
        "failedDeletionJobId": failed_job.id,
        "origin": settings.public_origin,
        "rootPath": settings.root_path,
        "ai": {
            "expectedStatus": "SUCCEEDED" if ai_configured else "FAILED",
            "expectedErrorCode": None if ai_configured else "AI_NOT_CONFIGURED",
        },
    }


def owned_accounts(db, manifest, run_id):
    data = manifest.data
    if (manifest.kind != "E2E_RUN" or manifest.version != run_id or manifest.verified
            or data.get("fixtureVersion") != FIXTURE_VERSION or data.get("runId") != run_id
            or set(data.get("accounts", {})) != set(ACCOUNT_NAMES)
            or data.get("signupLoginId") != run_id + "-signup"
            or set(data.get("referenceIds", [])) != {
                f"{run_id}-{name}" for name in REFERENCE_NAMES
            }):
        raise FixtureError("E2E 소유권 manifest가 올바르지 않아 정리하지 않았습니다.")
    result = set()
    for name, value in data["accounts"].items():
        if value.get("loginId") != f"{run_id}-{name}":
            raise FixtureError("E2E 계정 소유권이 변경되어 정리하지 않았습니다.")
        account = db.get(Account, value["accountId"])
        if account is None or account.login_id != value["loginId"]:
            raise FixtureError("E2E 계정 소유권이 변경되어 정리하지 않았습니다.")
        result.add(account.id)
    signup = db.scalar(select(Account).where(Account.login_id == data["signupLoginId"]))
    if signup:
        result.add(signup.id)
    for reference_id in data["referenceIds"]:
        reference = db.get(ReferenceData, reference_id)
        if not reference or reference.version != run_id:
            raise FixtureError("E2E 기준 자료 소유권이 변경되어 정리하지 않았습니다.")
    return result


def cleanup_attempt(settings, factory, run_id):
    with factory() as db, db.begin():
        validate_environment(settings, db.connection())
        lock(db, "e2e-cleanup", run_id)
        manifest = db.get(ReferenceData, run_id + "-manifest")
        if manifest is None:
            return {"status": "not_found", "runId": run_id}
        account_ids = owned_accounts(db, manifest, run_id)
        resources = list(db.scalars(select(Resource).where(Resource.owner_id.in_(account_ids))))
        resource_ids = {row.id for row in resources}
        jobs = list(db.scalars(select(Job).where(Job.id.in_(resource_ids))))
        if any(job.state in ("QUEUED", "RUNNING") for job in jobs):
            return None

        # 외부 소유 자료가 생겼다면 CASCADE로 함께 지우지 않고 사람이 확인하도록 남긴다.
        linked = or_(
            Resource.request_id.in_(resource_ids), Resource.item_id.in_(resource_ids),
            Resource.technician_id.in_(resource_ids), Resource.parent_id.in_(resource_ids),
        )
        if db.scalar(select(Resource.id).where(Resource.id.not_in(resource_ids), linked)):
            raise FixtureError("다른 계정 자료가 E2E 자원을 참조하여 정리하지 않았습니다.")
        files = list(db.scalars(select(StoredFile).where(StoredFile.resource_id.in_(resource_ids))))
        file_keys = {file.key for file in files}
        for job in jobs:
            # 교체된 사진의 옛 파일도 완료·실패한 FILE_CLEANUP payload에서 회수한다.
            if job.kind == "DELETE":
                file_keys.update(job.payload.get("fileKeys", []))
                for target_id in job.payload.get("resourceIds", []):
                    target = db.get(Resource, target_id)
                    if target and target.id not in resource_ids:
                        raise FixtureError("삭제 작업이 외부 자원을 참조하여 정리하지 않았습니다.")
        if db.scalar(select(StoredFile.id).where(
            StoredFile.key.in_(file_keys), StoredFile.resource_id.not_in(resource_ids),
        )):
            raise FixtureError("다른 계정 파일이 포함되어 정리하지 않았습니다.")

        store = FileStore(settings.storage_dir)
        for key in file_keys:
            store.delete(key)
        db.execute(delete(StoredFile).where(StoredFile.resource_id.in_(resource_ids)))
        db.execute(delete(Job).where(Job.id.in_(resource_ids)))
        db.execute(delete(Resource).where(Resource.id.in_(resource_ids)))
        db.execute(delete(Account).where(Account.id.in_(account_ids)))
        db.execute(delete(ReferenceData).where(
            ReferenceData.id.in_([*manifest.data["referenceIds"], manifest.id]),
        ))
        return {
            "status": "cleaned", "runId": run_id,
            "accounts": len(account_ids), "resources": len(resource_ids), "files": len(file_keys),
        }


def cleanup(settings, factory, run_id, wait_seconds=30):
    validate_run_id(run_id)
    deadline = time.monotonic() + wait_seconds
    while True:
        result = cleanup_attempt(settings, factory, run_id)
        if result is not None:
            return result
        if time.monotonic() >= deadline:
            raise FixtureError(
                "실행 대기·처리 중인 E2E 작업이 남아 정리하지 않았습니다. "
                "worker 상태를 확인한 뒤 같은 run ID로 정리를 다시 실행하세요."
            )
        time.sleep(min(1, max(0, deadline - time.monotonic())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "prepare", "cleanup"))
    parser.add_argument("run_id")
    arguments = parser.parse_args()
    database_engine = None
    try:
        validate_run_id(arguments.run_id)
        settings = get_settings()
        if settings.environment not in ("development", "test"):
            raise FixtureError("E2E는 development/test 환경에서만 허용합니다.")
        database_engine = engine()
        action = {"check": check, "prepare": prepare, "cleanup": cleanup}[arguments.action]
        result = action(settings, session_factory(), arguments.run_id)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except FixtureError as error:
        print(f"E2E fixture: {error}", file=sys.stderr)
    except Exception as error:
        # DB 연결 오류·SQLAlchemy 오류의 문자열은 접속 정보나 임시 비밀번호를 포함할 수 있다.
        print(f"E2E fixture 실패 ({type(error).__name__}). 컨테이너 상태를 확인하세요.", file=sys.stderr)
    finally:
        if database_engine is not None:
            database_engine.dispose()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
