import json
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db import Account, Job, ReferenceData, Resource, StoredFile
from app.main import create_app
from app.schema import alembic_config
from app.services.context import Context
from app.time_rules import SEOUL, iso
from app.worker import run_once
from conftest import APIClient, login, picture, result, setup_item
from scripts import seed_initial
from test_api import consultation_and_quote


def test_seed_script_path_runs_from_parent_directory():
    script = Path(seed_initial.__file__).resolve()
    parent_directory = script.parents[2]
    completed = subprocess.run(
        [
            "uv", "run", "--no-env-file", "--no-project", "--offline",
            "--python", sys.executable, "python", "-E",
            str(script.relative_to(parent_directory)), "--help",
        ],
        cwd=parent_directory,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--help" in completed.stdout


@pytest.fixture
def seed_environment(tmp_path):
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'seed.db'}",
        storage_dir=tmp_path / "media",
        log_dir=tmp_path / "logs",
        public_origin="http://testserver",
        seed_password="testing-password-123",
    )
    engine = create_engine(settings.database_url.get_secret_value())
    with engine.begin() as connection:
        config = alembic_config()
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    yield settings, sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


def test_new_user_can_find_seeded_technician_and_confirm_reservation(seed_environment):
    settings, factory = seed_environment
    seeded = seed_initial.seed_initial(settings, factory)
    assert seeded.created
    assert seeded.generated_password is None
    with factory() as db:
        accounts = list(db.scalars(select(Account)))
        tech_accounts = [row for row in accounts if "TECHNICIAN" in row.roles]
        user_only_accounts = [row for row in accounts if "TECHNICIAN" not in row.roles]
        assert len(tech_accounts) == 32
        assert {row.login_id for row in user_only_accounts} == {
            seed_initial.SCENARIO2_COMPETITOR_USER_LOGIN,
            seed_initial.SCENARIO3_USER_LOGIN,
        }
        assert list(db.scalars(select(Job).where(Job.state != "DONE"))) == []

    app = create_app(settings, factory)
    with APIClient(app) as user, APIClient(app) as technician:
        result(user.post("/v1/auth/signup", json={
            "loginId": "new-user", "password": "testing-password-123",
        }), status=201)
        login(user, "new-user")
        login(technician, seed_initial.DEMO_LOGIN, "TECHNICIAN")
        tech = result(technician.get("/v1/technicians/me"), "TechnicianDTO")
        technician_id = tech["technicianId"]
        service = result(user.get("/v1/public/service-info"))
        region = next(r for r in service["regions"] if r["neighborhood"] == "연남동")
        portfolio = result(user.get(f"/v1/technicians/{technician_id}/portfolio"), "PortfolioDTO")
        case, = portfolio["cases"]
        assert case["content"]["dataType"] == "MOCK"
        for photo in (case["beforePhotos"][0], case["afterPhotos"][0]):
            response = user.get(f"/v1/media/{photo['mediaId']}")
            assert response.status_code == 200
            assert response.headers["content-type"] == "image/jpeg"

        root = result(user.post(
            "/v1/requests",
            headers={"Idempotency-Key": '"new-demo-request"'},
            data={"metadata": json.dumps({
                "symptom": "싱크대 수전에서 물이 샙니다.",
                "region": {key: region[key] for key in ("city", "district", "neighborhood", "regionId")},
                "photos": [{"capturedOn": None, "dateConfirmed": False, "description": "수전 사진"}],
            })},
            files=[("files", ("sink.png", picture(), "image/png"))],
        ), "RequestDTO", 201)
        root, item, start = setup_item(user, root, visit_address="서울특별시 마포구 연남동 101호")
        item_path = f"/v1/work-items/{item['workItemId']}"
        candidates = result(user.get(f"{item_path}/general-candidates"))
        match = next(
            row for row in candidates["items"] if row["technician"]["technicianId"] == technician_id
        )
        assert match["timeFit"] == "MATCHED"
        root, _, quote, _ = consultation_and_quote(
            user, technician, (settings, factory, app), root, item, start, tech,
        )
        reservation = result(user.post(
            f"{item_path}/reservations",
            headers={"Idempotency-Key": '"demo-reservation"'},
            json={"quoteId": quote["quoteId"], "versions": quote["terms"]["versions"],
                  "visitDetailsRevision": root["visitDetailsRevision"]},
        ), "ReservationDTO", 201)
        assert reservation["status"] == "CONFIRMED"


def test_scenario_1_sliding_door_candidates_cases_and_single_photo_consultation(seed_environment):
    settings, factory = seed_environment
    seeded = seed_initial.seed_initial(settings, factory)
    saturday = seeded.scenario_saturday
    assert saturday is not None and saturday.weekday() == seed_initial.SATURDAY

    app = create_app(settings, factory)
    with APIClient(app) as minseo, APIClient(app) as tech_a, APIClient(app) as tech_b, APIClient(app) as tech_c:
        result(minseo.post("/v1/auth/signup", json={
            "loginId": "minseo", "password": "testing-password-123",
        }), status=201)
        login(minseo, "minseo")
        ids = {}
        for key, client, login_id in (
            ("A", tech_a, seed_initial.SCENARIO1_TECH_A_LOGIN),
            ("B", tech_b, seed_initial.SCENARIO1_TECH_B_LOGIN),
            ("C", tech_c, seed_initial.SCENARIO1_TECH_C_LOGIN),
        ):
            login(client, login_id, "TECHNICIAN")
            ids[key] = result(client.get("/v1/technicians/me"), "TechnicianDTO")["technicianId"]

        service = result(minseo.get("/v1/public/service-info"))
        yeonnam = next(r for r in service["regions"] if r["neighborhood"] == "연남동")
        root = result(minseo.post(
            "/v1/requests",
            headers={"Idempotency-Key": '"s1-request"'},
            data={"metadata": json.dumps({
                "symptom": "열 때는 괜찮은데, 닫히기 10cm쯤 전부터 바닥을 긁으면서 걸려요.",
                "region": {k: yeonnam[k] for k in ("city", "district", "neighborhood", "regionId")},
                "photos": [
                    {"capturedOn": None, "dateConfirmed": False, "description": "거실 미닫이문 전체 사진"},
                    {"capturedOn": None, "dateConfirmed": False, "description": "미닫이문 하단 레일 사진"},
                ],
            })},
            files=[
                ("files", ("door-full.png", picture("blue"), "image/png")),
                ("files", ("door-rail.png", picture("green"), "image/png")),
            ],
        ), "RequestDTO", 201)
        item = root["workItems"][0]
        rail_photo = next(
            p for p in root["photos"]["unknownDatePhotos"] if "레일" in (p["description"] or "")
        )
        item = result(minseo.patch(f"/v1/work-items/{item['workItemId']}", json={
            "expectedRevision": item["revision"],
            "facts": {
                "part": "거실 미닫이문 하단 레일",
                "workType": "미닫이문 수리",
                "quantity": 1,
                "fields": ["DOORS_WINDOWS"],
                "visitPreference": {
                    "mode": "FLEXIBLE",
                    "fixedStartAt": None,
                    "ranges": [{
                        "startAt": iso(datetime.combine(saturday, time(14, 0), SEOUL)),
                        "endAt": iso(datetime.combine(saturday, time(17, 0), SEOUL)),
                    }],
                },
            },
            "resolutionPath": "TECHNICIAN",
        }), "WorkItemDTO")
        item = result(minseo.put(
            f"/v1/work-items/{item['workItemId']}/confirmation",
            headers={"Idempotency-Key": '"s1-confirm"'},
            json={
                "expectedRevision": item["revision"],
                "sourceRevision": item["sourceRevision"],
                "fields": ["DOORS_WINDOWS"],
                "confirmed": True,
                "summary": {
                    "text": "거실 미닫이문이 닫히기 10cm 전부터 바닥을 긁으며 걸림. 원인은 현장 점검 필요.",
                    "facts": [],
                    "unknowns": ["정확한 마모·변형 부위"],
                    "riskSignals": [],
                    "limitations": [],
                    "onsiteInspectionNeeded": True,
                },
            },
        ), "WorkItemDTO")

        candidates = result(minseo.get(f"/v1/work-items/{item['workItemId']}/general-candidates"))
        fits = {row["technician"]["technicianId"]: row["timeFit"] for row in candidates["items"]}
        assert fits == {ids["A"]: "MATCHED", ids["B"]: "MATCHED", ids["C"]: "NOT_MATCHED"}

        # 사례 매칭 실행 시 A만 3점 이상 + MATCHED로 추천되고, B(2점)와 C(NOT_MATCHED)는 제외된다.
        portfolio_a = result(minseo.get(f"/v1/technicians/{ids['A']}/portfolio"), "PortfolioDTO")
        portfolio_b = result(minseo.get(f"/v1/technicians/{ids['B']}/portfolio"), "PortfolioDTO")
        portfolio_c = result(minseo.get(f"/v1/technicians/{ids['C']}/portfolio"), "PortfolioDTO")
        assert portfolio_a["cases"][0]["content"]["confirmedCause"] == "하부 롤러 마모"
        assert portfolio_b["cases"][0]["content"]["confirmedCause"] == "창문 잠금장치 파손"
        assert portfolio_c["cases"][0]["content"]["confirmedCause"] == "하단 레일 변형"

        ai_job = result(minseo.post(
            f"/v1/requests/{root['requestId']}/ai-jobs",
            headers={"Idempotency-Key": '"s1-case-match"'},
            json={"type": "CASE_MATCHING", "workItemId": item["workItemId"], "sourceRevision": item["sourceRevision"]},
        ), "AiJobDTO", 202)
        by_id = {row["technician"]["technicianId"]: row for row in candidates["items"]}
        mock_ai_output = {
            "summary": None, "fieldCandidates": [], "question": None,
            "guideExplanation": None, "comparison": None, "reportDraft": None,
            "caseRecommendations": {
                "evaluationStatus": "COMPLETED",
                "sourceRevision": item["sourceRevision"],
                "stale": False,
                "reason": None,
                "recommendations": [
                    {
                        "candidate": by_id[ids["A"]],
                        "rank": 1,
                        "averageScore": 5.0,
                        "cases": [{
                            "case": portfolio_a["cases"][0],
                            "score": 5,
                            "evidence": [
                                "닫힘 직전 걸림과 하단 긁힘이 과거 모의 사례와 유사합니다.",
                                "당시에는 하부 롤러 마모가 확인됐으며, 현재 요청의 원인은 현장 점검이 필요합니다.",
                            ],
                        }],
                    },
                    {
                        "candidate": by_id[ids["B"]],
                        "rank": 2,
                        "averageScore": 2.0,
                        "cases": [{"case": portfolio_b["cases"][0], "score": 2, "evidence": ["분야만 유사"]}],
                    },
                    {
                        "candidate": by_id[ids["C"]],
                        "rank": 3,
                        "averageScore": 4.0,
                        "cases": [{"case": portfolio_c["cases"][0], "score": 4, "evidence": ["닫힘 직전 걸림 유사"]}],
                    },
                ],
            },
        }
        assert run_once(factory, settings, provider=lambda *_: mock_ai_output)
        recs = result(minseo.get(f"/v1/work-items/{item['workItemId']}/case-recommendations"), "CaseRecommendationsDTO")
        assert [r["candidate"]["technician"]["technicianId"] for r in recs["recommendations"]] == [ids["A"]]

        # 민서는 레일 사진 1장만 담은 상담 전달본을 준비·확인해 A에게 상담을 요청한다.
        delivery = result(minseo.post(
            f"/v1/work-items/{item['workItemId']}/deliveries",
            headers={"Idempotency-Key": '"s1-delivery"'},
            json={
                "sourceRevision": item["sourceRevision"],
                "scope": {
                    "purpose": "CONSULTATION",
                    "recipientTechnicianId": ids["A"],
                    "photoIds": [rail_photo["photoId"]],
                    "recordIds": [],
                    "questionIds": [],
                    "includeSummary": True,
                    "includeReport": False,
                    "includeQuoteContext": True,
                },
                "redactions": [],
            },
        ), "DeliveryDTO", 202)
        assert run_once(factory, settings)
        delivery = result(minseo.get(f"/v1/deliveries/{delivery['deliveryId']}"), "DeliveryDTO")
        delivery = result(minseo.put(
            f"/v1/deliveries/{delivery['deliveryId']}/confirmation",
            headers={"Idempotency-Key": '"s1-delivery-confirm"'},
            json={"expectedRevision": delivery["revision"], "sourceRevision": item["sourceRevision"], "confirmed": True},
        ), "DeliveryDTO")
        relation = result(minseo.post(
            f"/v1/work-items/{item['workItemId']}/consultations",
            headers={"Idempotency-Key": '"s1-consult"'},
            json={"technicianId": ids["A"], "deliveryId": delivery["deliveryId"]},
        ), "ConsultationDTO", 201)
        assert relation["status"] == "PENDING"
        delivered_for_a = result(tech_a.get(f"/v1/deliveries/{delivery['deliveryId']}"), "DeliveryDTO")
        assert [p["photoId"] for p in delivered_for_a["content"]["photos"]] == [rail_photo["photoId"]]


def test_scenario_2_route_discount_ranking_and_schedule_conflict(seed_environment):
    settings, factory = seed_environment
    seeded = seed_initial.seed_initial(settings, factory)
    thursday = seeded.scenario_thursday
    assert thursday is not None and thursday.weekday() == seed_initial.THURSDAY

    app = create_app(settings, factory)
    with APIClient(app) as jihoon, APIClient(app) as technician:
        result(jihoon.post("/v1/auth/signup", json={
            "loginId": "jihoon", "password": "testing-password-123",
        }), status=201)
        login(jihoon, "jihoon")
        login(technician, seed_initial.DEMO_LOGIN, "TECHNICIAN")
        tech = result(technician.get("/v1/technicians/me"), "TechnicianDTO")

        service = result(jihoon.get("/v1/public/service-info"))
        yeonnam = next(r for r in service["regions"] if r["neighborhood"] == "연남동")
        root = result(jihoon.post(
            "/v1/requests",
            headers={"Idempotency-Key": '"s2-request"'},
            data={"metadata": json.dumps({
                "symptom": "연남동 싱크대 수전 한 개를 교체하려고 합니다.",
                "region": {k: yeonnam[k] for k in ("city", "district", "neighborhood", "regionId")},
                "photos": [{"capturedOn": None, "dateConfirmed": False, "description": "싱크대 수전"}],
            })},
            files=[("files", ("faucet.png", picture("cyan"), "image/png"))],
        ), "RequestDTO", 201)
        item = root["workItems"][0]
        item = result(jihoon.patch(f"/v1/work-items/{item['workItemId']}", json={
            "expectedRevision": item["revision"],
            "facts": {
                "part": "싱크대 수전",
                "workType": "수전 교체",
                "quantity": 1,
                "fields": ["PLUMBING"],
                "visitPreference": {
                    "mode": "FLEXIBLE",
                    "fixedStartAt": None,
                    "ranges": [{
                        "startAt": iso(datetime.combine(thursday, time(14, 0), SEOUL)),
                        "endAt": iso(datetime.combine(thursday, time(17, 0), SEOUL)),
                    }],
                },
            },
            "resolutionPath": "TECHNICIAN",
        }), "WorkItemDTO")
        item = result(jihoon.put(
            f"/v1/work-items/{item['workItemId']}/confirmation",
            headers={"Idempotency-Key": '"s2-confirm"'},
            json={
                "expectedRevision": item["revision"],
                "sourceRevision": item["sourceRevision"],
                "fields": ["PLUMBING"],
                "confirmed": True,
                "summary": {
                    "text": "연남동 싱크대 수전 1개 교체 요청.",
                    "facts": [],
                    "unknowns": ["기존 수전 체결 상태"],
                    "riskSignals": [],
                    "limitations": [],
                    "onsiteInspectionNeeded": True,
                },
            },
        ), "WorkItemDTO")
        item = result(jihoon.put(
            f"/v1/work-items/{item['workItemId']}/route-exploration",
            headers={"Idempotency-Key": '"s2-route-on"'},
            json={"expectedRevision": item["revision"], "enabled": True, "confirmed": True},
        ), "WorkItemDTO")
        assert item["routeExplorationEnabled"] is True

        # 동선 추천에서 연남동(+15분)이 합정동(+30분)보다 먼저 노출된다.
        route_page = result(technician.get(
            "/v1/technicians/me/route-candidates",
            params={"date": thursday.isoformat()},
        ))
        items = route_page["items"]
        assert [(row["region"]["neighborhood"], row["route"]["additionalMinutes"]) for row in items[:2]] == [
            ("연남동", 15),
            ("합정동", 30),
        ]
        yeonnam_candidate = items[0]
        interest = result(technician.post(
            f"/v1/route-candidates/{yeonnam_candidate['candidateId']}/interests",
            headers={"Idempotency-Key": '"s2-interest"'},
        ), status=201)
        assert interest["technician"]["technicianId"] == tech["technicianId"]

        # 지훈이 전달본 확인 후 상담 요청 → 기사 수락 → 14:45 시작안 차단 확인 → 14:00 할인 견적 확정
        delivery = result(jihoon.post(
            f"/v1/work-items/{item['workItemId']}/deliveries",
            headers={"Idempotency-Key": '"s2-delivery"'},
            json={
                "sourceRevision": item["sourceRevision"],
                "scope": {
                    "purpose": "CONSULTATION",
                    "recipientTechnicianId": tech["technicianId"],
                    "photoIds": [root["photos"]["unknownDatePhotos"][0]["photoId"]],
                    "recordIds": [],
                    "questionIds": [],
                    "includeSummary": True,
                    "includeReport": False,
                    "includeQuoteContext": True,
                },
                "redactions": [],
            },
        ), "DeliveryDTO", 202)
        assert run_once(factory, settings)
        delivery = result(jihoon.get(f"/v1/deliveries/{delivery['deliveryId']}"), "DeliveryDTO")
        delivery = result(jihoon.put(
            f"/v1/deliveries/{delivery['deliveryId']}/confirmation",
            headers={"Idempotency-Key": '"s2-delivery-confirm"'},
            json={"expectedRevision": delivery["revision"], "sourceRevision": item["sourceRevision"], "confirmed": True},
        ), "DeliveryDTO")
        relation = result(jihoon.post(
            f"/v1/work-items/{item['workItemId']}/consultations",
            headers={"Idempotency-Key": '"s2-consult"'},
            json={"technicianId": tech["technicianId"], "deliveryId": delivery["deliveryId"]},
        ), "ConsultationDTO", 201)
        relation = result(technician.patch(
            f"/v1/consultations/{relation['consultationId']}",
            headers={"Idempotency-Key": '"s2-accept"'},
            json={"expectedRevision": relation["revision"], "action": "ACCEPT"},
        ), "ConsultationDTO")
        root = result(jihoon.get(f"/v1/requests/{root['requestId']}"), "RequestDTO")

        base_cost = {
            "minimumVisitFee": 10000,
            "minimumDiagnosticFee": 0,
            "lines": [
                {"category": "LABOR", "description": "수전 교체 공임", "confirmed": True, "beforeAmount": 50000, "afterAmount": 50000, "condition": None},
                {"category": "VISIT", "description": "출장비", "confirmed": True, "beforeAmount": 20000, "afterAmount": 10000, "condition": None},
                {"category": "PART", "description": "싱크대 수전 부품비", "confirmed": True, "beforeAmount": 30000, "afterAmount": 30000, "condition": None},
            ],
            "discountCondition": "목요일 14:00 기존 출장 사이 방문 시 출장비 1만 원 할인",
        }
        # 14:45 시작안은 15:45 종료 + 30분 이동 = 16:15 > 16:00 서교동 다음 방문과 충돌해 차단된다.
        late_start = datetime.combine(thursday, time(14, 45), SEOUL)
        late_response = technician.post(
            f"/v1/consultations/{relation['consultationId']}/quotes",
            headers={"Idempotency-Key": '"s2-quote-late"'},
            json={
                "contextDeliveryId": delivery["deliveryId"],
                "terms": {
                    "versions": {"commonVersion": root["commonVersion"], "itemVersion": item["itemVersion"], "proposalVersion": None},
                    "fields": ["PLUMBING"],
                    "scope": "싱크대 수전 1개 교체",
                    "quantity": 1,
                    "durationMinutes": 60,
                    "startAt": iso(late_start),
                    "expiresAt": iso(late_start - timedelta(minutes=30)),
                    "cost": base_cost,
                },
            },
        )
        assert late_response.status_code == 409
        assert late_response.json()["code"] == "TECHNICIAN_CONFLICT"

        # 14:00 시작안은 통과하고 할인 전 10만 → 9만(10.0% 할인)으로 예약 확정된다.
        good_start = datetime.combine(thursday, time(14, 0), SEOUL)
        quote = result(technician.post(
            f"/v1/consultations/{relation['consultationId']}/quotes",
            headers={"Idempotency-Key": '"s2-quote-ok"'},
            json={
                "contextDeliveryId": delivery["deliveryId"],
                "terms": {
                    "versions": {"commonVersion": root["commonVersion"], "itemVersion": item["itemVersion"], "proposalVersion": None},
                    "fields": ["PLUMBING"],
                    "scope": "싱크대 수전 1개 교체",
                    "quantity": 1,
                    "durationMinutes": 60,
                    "startAt": iso(good_start),
                    "expiresAt": iso(good_start - timedelta(minutes=30)),
                    "cost": base_cost,
                },
            },
        ), "QuoteDTO", 201)
        assert quote["price"] == {
            "beforeTotal": 100000,
            "afterTotal": 90000,
            "discountAmount": 10000,
            "discountRate": 10.0,
            "minimumTotal": 10000,
        }

        root = result(jihoon.put(
            f"/v1/requests/{root['requestId']}/visit-details",
            json={
                "expectedRevision": root["revision"],
                "confirmed": True,
                "visitDetails": {"address": "서울특별시 마포구 연남동 202호", "contact": "010-0000-0202"},
            },
        ), "RequestDTO")
        reservation = result(jihoon.post(
            f"/v1/work-items/{item['workItemId']}/reservations",
            headers={"Idempotency-Key": '"s2-reserve"'},
            json={
                "quoteId": quote["quoteId"],
                "versions": quote["terms"]["versions"],
                "visitDetailsRevision": root["visitDetailsRevision"],
            },
        ), "ReservationDTO", 201)
        assert reservation["status"] == "CONFIRMED"


def test_scenario_3_wallpaper_progress_pdf_handover_and_preparation_notes(seed_environment):
    settings, factory = seed_environment
    if not settings.pdf_font.is_file():
        settings.pdf_font = Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf")
    seed_initial.seed_initial(settings, factory)

    app = create_app(settings, factory)
    with APIClient(app) as seoyeon, APIClient(app) as wall_tech:
        login(seoyeon, seed_initial.SCENARIO3_USER_LOGIN)
        login(wall_tech, seed_initial.SCENARIO3_TECH_LOGIN, "TECHNICIAN")

        listing = result(seoyeon.get("/v1/requests"))
        assert len(listing["items"]) == 1
        root = result(seoyeon.get(f"/v1/requests/{listing['items'][0]['requestId']}"), "RequestDTO")
        item = root["workItems"][0]
        timeline = result(seoyeon.get(f"/v1/requests/{root['requestId']}/timeline"), "TimelineDTO")
        photos = timeline["photos"]["confirmedDatePhotos"]
        assert len(photos) == 3
        assert len(timeline["records"]) == 3
        group = timeline["groups"][0]
        assert group["comparisonPhotoIds"] == [photos[0]["photoId"], photos[2]["photoId"]]

        # 1일차-3일차 비교쌍으로 변경 가능하며, 1일차-4일차로 되돌린 뒤 보고서 확정·PDF·기사 인계까지 수행한다.
        timeline = result(seoyeon.put(
            f"/v1/requests/{root['requestId']}/photo-groups",
            json={
                "sourceRevision": timeline["sourceRevision"],
                "groups": [{
                    "groupId": group["groupId"],
                    "label": group["label"],
                    "photoIds": [p["photoId"] for p in photos],
                    "selectedPhotoIds": [photos[0]["photoId"], photos[1]["photoId"]],
                }],
            },
        ), "TimelineDTO")
        assert timeline["groups"][0]["comparisonPhotoIds"] == [photos[0]["photoId"], photos[1]["photoId"]]

        timeline = result(seoyeon.put(
            f"/v1/requests/{root['requestId']}/photo-groups",
            json={
                "sourceRevision": timeline["sourceRevision"],
                "groups": [{
                    "groupId": group["groupId"],
                    "label": group["label"],
                    "photoIds": [p["photoId"] for p in photos],
                    "selectedPhotoIds": [photos[0]["photoId"], photos[2]["photoId"]],
                }],
            },
        ), "TimelineDTO")
        root = result(seoyeon.get(f"/v1/requests/{root['requestId']}"), "RequestDTO")
        item = root["workItems"][0]

        report = result(seoyeon.put(
            f"/v1/work-items/{item['workItemId']}/report",
            json={
                "expectedRevision": None,
                "sourceRevision": item["sourceRevision"],
                "report": {
                    "markdown": "# 거실 창문 왼쪽 아래 벽지 물자국 경과 보고서\n\n- 4일차 사진에서 물자국이 아래쪽으로 넓게 보임.\n- 3일차에 비가 왔고 환기 후에도 자국이 남았다고 사용자가 기록함.\n- 원인은 현장 확인 필요.",
                    "photoIds": [photos[0]["photoId"], photos[2]["photoId"]],
                    "facts": [{
                        "text": "1일차와 4일차 동일 구도 비교에서 아래쪽 물자국 영역이 넓어 보임.",
                        "sourceType": "OBSERVATION",
                        "photoIds": [photos[0]["photoId"], photos[2]["photoId"]],
                        "recordIds": [],
                        "performanceReservationIds": [],
                    }],
                    "unknowns": ["내부 누수·결로 원인 (현장 점검 필요)"],
                },
            },
        ), "ReportDTO")
        report = result(seoyeon.put(
            f"/v1/work-items/{item['workItemId']}/report/confirmation",
            headers={"Idempotency-Key": '"s3-report-confirm"'},
            json={"expectedRevision": report["revision"], "sourceRevision": item["sourceRevision"], "confirmed": True},
        ), "ReportDTO")
        assert report["reviewStatus"] == "CONFIRMED"

        # 집주인 공유용 EXTERNAL_PDF 생성 및 다운로드
        pdf_delivery = result(seoyeon.post(
            f"/v1/work-items/{item['workItemId']}/deliveries",
            headers={"Idempotency-Key": '"s3-pdf-delivery"'},
            json={
                "sourceRevision": item["sourceRevision"],
                "scope": {
                    "purpose": "EXTERNAL_PDF",
                    "photoIds": [photos[0]["photoId"], photos[2]["photoId"]],
                    "recordIds": [],
                    "questionIds": [],
                    "includeSummary": False,
                    "includeReport": True,
                    "includeQuoteContext": False,
                },
                "redactions": [],
            },
        ), "DeliveryDTO", 202)
        assert run_once(factory, settings)
        pdf_delivery = result(seoyeon.get(f"/v1/deliveries/{pdf_delivery['deliveryId']}"), "DeliveryDTO")
        pdf_delivery = result(seoyeon.put(
            f"/v1/deliveries/{pdf_delivery['deliveryId']}/confirmation",
            headers={"Idempotency-Key": '"s3-pdf-delivery-confirm"'},
            json={"expectedRevision": pdf_delivery["revision"], "sourceRevision": item["sourceRevision"], "confirmed": True},
        ), "DeliveryDTO")
        pdf_job = result(seoyeon.post(
            f"/v1/deliveries/{pdf_delivery['deliveryId']}/pdf-jobs",
            headers={"Idempotency-Key": '"s3-pdf-job"'},
            json={"deliveryRevision": pdf_delivery["revision"]},
        ), "PdfJobDTO", 202)
        assert run_once(factory, settings)
        pdf_job = result(seoyeon.get(f"/v1/pdf-jobs/{pdf_job['jobId']}"), "PdfJobDTO")
        assert pdf_job["status"] == "READY" and pdf_job["downloadAvailable"] is True
        pdf_bytes = seoyeon.get(f"/v1/pdf-jobs/{pdf_job['jobId']}/content")
        assert pdf_bytes.status_code == 200 and pdf_bytes.content.startswith(b"%PDF")

        # 확정 예약 기사에게 HANDOVER 전달본 공유 및 기사 방문 준비사항 등록
        reservation_id = item["activeReservationId"]
        assert reservation_id is not None
        reservation = result(seoyeon.get(f"/v1/reservations/{reservation_id}"), "ReservationDTO")
        handover_delivery = result(seoyeon.post(
            f"/v1/work-items/{item['workItemId']}/deliveries",
            headers={"Idempotency-Key": '"s3-handover-delivery"'},
            json={
                "sourceRevision": item["sourceRevision"],
                "scope": {
                    "purpose": "HANDOVER",
                    "recipientTechnicianId": reservation["technicianId"],
                    "reservationId": reservation_id,
                    "photoIds": [photos[0]["photoId"], photos[2]["photoId"]],
                    "recordIds": [],
                    "questionIds": [],
                    "includeSummary": False,
                    "includeReport": True,
                    "includeQuoteContext": False,
                },
                "redactions": [],
            },
        ), "DeliveryDTO", 202)
        assert run_once(factory, settings)
        handover_delivery = result(seoyeon.get(f"/v1/deliveries/{handover_delivery['deliveryId']}"), "DeliveryDTO")
        handover_delivery = result(seoyeon.put(
            f"/v1/deliveries/{handover_delivery['deliveryId']}/confirmation",
            headers={"Idempotency-Key": '"s3-handover-confirm"'},
            json={"expectedRevision": handover_delivery["revision"], "sourceRevision": item["sourceRevision"], "confirmed": True},
        ), "DeliveryDTO")

        tech_handover = result(wall_tech.get(f"/v1/deliveries/{handover_delivery['deliveryId']}"), "DeliveryDTO")
        assert tech_handover["content"]["report"]["content"]["markdown"].startswith("# 거실 창문 왼쪽 아래")
        prep = result(wall_tech.put(
            f"/v1/reservations/{reservation_id}/preparation-notes",
            json={
                "preparation": {
                    "equipment": ["수분측정기"],
                    "parts": [],
                    "inspectionItems": ["창틀 주변과 벽지 물자국 경계를 함께 점검"],
                    "note": "창틀 주변과 벽지 물자국 경계를 함께 점검",
                },
            },
        ), "PreparationDTO")
        assert "창틀 주변과 벽지 물자국 경계를 함께 점검" in prep["inspectionItems"]


def test_rerun_reuses_reference_data_and_only_extends_unedited_schedules(seed_environment):
    settings, factory = seed_environment
    today = date(2030, 1, 1)
    with factory.begin() as db:
        db.add(ReferenceData(
            id="existing-yeonnam", kind="REGION", version="existing", verified=True,
            data={"city": "서울특별시", "district": "마포구", "neighborhood": "연남동",
                  "representativeLocationId": "existing-location"},
        ))
    seed_initial.seed_initial(settings, factory, today)
    same_day = seed_initial.seed_initial(settings, factory, today)
    assert not same_day.created and same_day.schedules_extended == 0

    with factory.begin() as db:
        manifest = db.get(ReferenceData, seed_initial.SEED_VERSION)
        edited_id, untouched_id = [row["id"] for row in manifest.data["schedules"][:2]]
        edited = db.get(Resource, edited_id)
        assert edited.data["departureLocationId"] == "existing-location"
        assert db.get(ReferenceData, f"{seed_initial.SEED_VERSION}-region-yeonnam") is None
        Context(db, None, settings).save(edited, availability=[])
        account_ids = set(db.scalars(select(Account.id)))
        photo_ids = set(db.scalars(select(StoredFile.id)))

    refresh = seed_initial.seed_initial(settings, factory, today + timedelta(days=2))
    assert not refresh.created
    assert (refresh.schedules_extended, refresh.schedules_skipped) == (31, 1)
    assert refresh.available_through == today + timedelta(days=15)
    with factory() as db:
        assert db.get(Resource, edited_id).data["availability"] == []
        assert len(db.get(Resource, untouched_id).data["availability"]) == 16
        assert set(db.scalars(select(Account.id))) == account_ids
        assert set(db.scalars(select(StoredFile.id))) == photo_ids


def test_seed_failure_rolls_back_database_and_images(seed_environment, monkeypatch):
    settings, factory = seed_environment

    def fail_case(*args, **kwargs):
        raise RuntimeError("모의 사례 등록 오류")

    monkeypatch.setattr(seed_initial.technicians, "case", fail_case)
    with pytest.raises(RuntimeError, match="모의 사례 등록 오류"):
        seed_initial.seed_initial(settings, factory)

    with factory() as db:
        for model in (Account, Job, ReferenceData, Resource, StoredFile):
            assert db.scalar(select(model)) is None
    assert list(settings.storage_dir.iterdir()) == []
