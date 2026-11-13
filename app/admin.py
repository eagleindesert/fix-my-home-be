"""컨테이너 안에서 실행하는 계정 발급·검증 기준 자료 가져오기 CLI."""

import argparse
import json
from getpass import getpass
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.db import Account, ReferenceData, Resource, lock, session_factory, uid
from app.errors import require
from app.security import Actor, hash_password
from app.services.context import Context


def create_account(db, settings, login_id, password, roles):
    require(len(password) >= 12, "VALIDATION_ERROR", "비밀번호는 12자 이상이어야 합니다.", 422)
    require(set(roles) <= {"USER", "TECHNICIAN"} and roles, "VALIDATION_ERROR", "계정 역할을 확인하세요.", 422)
    require(not db.scalar(select(Account).where(Account.login_id == login_id)), "ACCOUNT_EXISTS", "이미 발급한 계정입니다.")
    account = Account(id=uid(), login_id=login_id, password_hash=hash_password(password), roles=roles)
    db.add(account)
    db.flush()
    if "TECHNICIAN" in roles:
        ctx = Context(db, Actor(account.id, "TECHNICIAN", None, None), settings)
        ctx.create("TECHNICIAN", {"profile": {"displayName": login_id, "fields": [], "regionIds": [],
                    "contacts": [], "representativeMediaIds": []}})
    return account


def import_references(db, bundle):
    require(bundle.get("version") and bundle.get("reviewedBy") and bundle.get("reviewedAt"),
            "REFERENCE_NOT_VERIFIED", "검증자·검증 시각·버전이 필요합니다.", 422)
    supported = {"REGION", "TRAVEL", "DURATION", "SOURCE", "GUIDANCE", "EMERGENCY_TRIGGER"}
    for entry in bundle["entries"]:
        require(entry["kind"] in supported and entry.get("source") and entry.get("verified") is True,
                "REFERENCE_NOT_VERIFIED", "확인한 출처와 검증 상태가 필요합니다.", 422)
        data = entry["data"]
        if entry["kind"] in ("TRAVEL", "DURATION"):
            require(type(data.get("minutes")) is int and data["minutes"] > 0 and data["minutes"] % 15 == 0,
                    "INVALID_REFERENCE", "모의 이동·소요 시간은 양수 15분 배수여야 합니다.", 422)
        if entry["kind"] == "REGION":
            require(all(data.get(k) for k in ("city", "district", "neighborhood", "representativeLocationId")), "INVALID_REFERENCE", "지역과 대표 위치가 필요합니다.", 422)
        row = db.get(ReferenceData, entry["id"])
        values = {"kind": entry["kind"], "version": bundle["version"], "verified": True,
                  "data": {**data, "provenance": {"source": entry["source"], "reviewedBy": bundle["reviewedBy"], "reviewedAt": bundle["reviewedAt"]}}}
        if row:
            for key, value in values.items():
                setattr(row, key, value)
        else:
            db.add(ReferenceData(id=entry["id"], **values))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    account = commands.add_parser("create-account")
    account.add_argument("login_id")
    account.add_argument("--roles", nargs="+", choices=["USER", "TECHNICIAN"], default=["USER"])
    references = commands.add_parser("import-references")
    references.add_argument("file", help="검증된 JSON 번들 파일. '-'는 표준 입력")
    location = commands.add_parser("set-technician-locations")
    location.add_argument("login_id")
    location.add_argument("departure")
    location.add_argument("return_location")
    args = parser.parse_args()
    settings = get_settings()
    with session_factory()() as db, db.begin():
        lock(db, "admin")
        if args.command == "create-account":
            password = settings.seed_password.get_secret_value() or getpass("발급할 비밀번호: ")
            create_account(db, settings, args.login_id, password, args.roles)
        elif args.command == "import-references":
            import sys
            import_references(db, json.load(sys.stdin) if args.file == "-" else json.loads(Path(args.file).read_text()))
        else:
            account = db.scalar(select(Account).where(Account.login_id == args.login_id))
            require(account, "RESOURCE_NOT_FOUND", "계정을 찾을 수 없습니다.", 404)
            tech = db.scalar(select(Resource).where(Resource.kind == "TECHNICIAN", Resource.owner_id == account.id))
            require(tech, "RESOURCE_NOT_FOUND", "기사 자원이 없습니다.", 404)
            ctx = Context(db, Actor(account.id, "TECHNICIAN", tech.id, None), settings)
            from app.services.reservations import validate_location
            from app.services.scheduling import schedule_resource
            validate_location(ctx, args.departure)
            validate_location(ctx, args.return_location)
            row = schedule_resource(ctx, tech)
            values = {"departureLocationId": args.departure, "returnLocationId": args.return_location}
            if row:
                ctx.save(row, **values)
            else:
                ctx.create("SCHEDULE", {"availability": [], "externalVisits": [], **values}, technician_id=tech.id)
    print("저장했습니다.")


if __name__ == "__main__":
    main()
