"""임시 SQLite DB와 실제 HTTP 서버/worker를 함께 실행한다. AI만 고정 응답이다."""

import argparse
import io
import os
import socket
import threading
from pathlib import Path

import uvicorn
from PIL import Image
from alembic import command
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.main import create_app
from app.schema import alembic_config
from app.worker import run_once
from scripts.e2e.fixtures import prepare


def diagnosis(_settings, prompt, photos, _remaining):
    """시나리오 입력에 연결한 고정 출력. 실제 모델 품질 평가는 별도로 수행한다."""
    result = {
        "summary": None, "fieldCandidates": [], "question": None,
        "guideExplanation": None, "caseRecommendations": None,
        "comparison": None, "reportDraft": None,
    }
    photo_ids = [photo["photoId"] for photo in prompt["photos"]]
    record_ids = [record["recordId"] for record in prompt["records"]]
    fact = {
        "text": "사용자가 사진과 함께 관찰 내용을 기록했습니다.",
        "sourceType": "USER_STATEMENT", "photoIds": photo_ids,
        "recordIds": record_ids, "performanceReservationIds": [],
    }
    kind = prompt["type"]
    if kind == "DIAGNOSIS":
        result.update({
            "summary": {
                "text": "E2E 가상 관찰입니다. 원인은 현장 점검이 필요합니다.",
                "facts": [fact], "unknowns": ["누수 원인"], "riskSignals": [],
                "limitations": ["E2E 고정 응답"], "onsiteInspectionNeeded": True,
            },
            "fieldCandidates": ["PLUMBING"],
        })
    elif kind == "QUESTION":
        result["question"] = {
            "questionId": "pending", "text": "물자국을 처음 발견한 시점과 발생 조건은 무엇인가요?",
            "options": [], "answer": None, "optionId": None, "skipped": False,
        }
    elif kind == "CASE_MATCHING":
        # 시스템은 아래 모델 후보를 실제 프로필·일정 검사 결과로 다시 치환한다.
        recommendations = []
        for case in prompt["cases"]:
            source = case["content"]["source"]
            if not prompt["item"]["facts"]["workType"].startswith(source["reference"]):
                continue
            candidate = {
                "technician": {
                    "technicianId": case["technicianId"], "displayName": "E2E 가상 기사",
                    "fields": case["content"]["fields"], "regions": [], "contacts": [],
                    "directContactAvailable": False, "visitAvailability": "UNKNOWN",
                },
                "matchedFields": case["content"]["fields"], "unsupportedFields": [],
                "timeFit": "UNKNOWN", "checks": [],
                "durationEstimate": {
                    "minutes": None, "referenceId": None,
                    "version": None, "technicianConfirmed": False,
                },
            }
            recommendations.append({
                "candidate": candidate,
                "cases": [{
                    "case": case, "score": 5,
                    "evidence": [case["content"]["initialSymptom"], case["content"]["workDescription"]],
                }],
                "averageScore": 5, "rank": len(recommendations) + 1,
            })
        result["caseRecommendations"] = {
            "evaluationStatus": "COMPLETED", "sourceRevision": prompt["item"]["sourceRevision"],
            "stale": False, "recommendations": recommendations,
            "reason": None if recommendations else "연관 사례가 없습니다.",
        }
    elif kind == "PHOTO_COMPARISON":
        group = prompt["group"]
        with (
            Image.open(io.BytesIO(photos[0]["bytes"])) as first,
            Image.open(io.BytesIO(photos[1]["bytes"])) as second,
        ):
            changed = first.convert("RGB").tobytes() != second.convert("RGB").tobytes()
            width, height = second.size
        comparable = group["chronologyKnown"]
        result["comparison"] = {
            "groupId": group["groupId"], "photoIds": group["comparisonPhotoIds"],
            "status": ("CHANGED" if changed else "UNCHANGED") if comparable else "INCOMPARABLE",
            "chronologyKnown": comparable, "causeUnknown": True,
            "regions": [{"photoId": photo_ids[1], "width": width, "height": height,
                         "box": [0.1, 0.1, 0.9, 0.9], "description": "합성 물자국 영역이 다릅니다."}]
                       if comparable and changed else [],
            "observations": [fact] if comparable else [],
            "reason": None if comparable else "촬영 순서를 확인할 수 없습니다.",
            "retakeGuide": [] if comparable else ["촬영일과 동일 부위 여부를 확인해 주세요."],
        }
    elif kind == "REPORT_DRAFT":
        dates = ", ".join(photo["capturedOn"] or "날짜 미확인" for photo in prompt["photos"])
        conditions = prompt["context"]["conditions"] or "발생 조건 미확인"
        result["reportDraft"] = {
            "markdown": (
                f"# 벽지 물자국 경과\n촬영일: {dates}\n증상: {prompt['symptom']}\n"
                f"발생 조건: {conditions}\n"
                "사용자가 기록을 보완했습니다. 내부 원인과 위험도는 현장 확인이 필요합니다."
            ),
            "photoIds": photo_ids, "facts": [fact], "unknowns": ["내부 원인", "현장 위험도"],
        }
    else:
        raise ValueError(f"E2E 고정 제공자가 지원하지 않는 유형: {kind}")
    return result


def find_font():
    configured = os.environ.get("FMH_PDF_FONT")
    if configured:
        if Path(configured).is_file():
            return Path(configured)
        raise RuntimeError("FMH_PDF_FONT에 지정한 폰트 파일이 없습니다.")
    for path in (
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    ):
        if Path(path).is_file():
            return Path(path)
    raise RuntimeError("PDF 한글 폰트가 필요합니다. FMH_PDF_FONT에 폰트 경로를 지정하세요.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    database = directory / "e2e.db"
    if database.exists():
        raise RuntimeError("기존 DB를 재사용하지 않습니다. 새 디렉터리를 지정하세요.")

    # 포트 선택과 바인딩을 한 번에 수행해 다른 프로세스와의 포트 경쟁을 피한다.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
        settings = Settings(
            environment="test", database_url=f"sqlite:///{database}",
            storage_dir=directory / "media", log_dir=directory / "logs",
            session_secret="e2e-isolated-session-secret", session_cookie="e2e_session",
            cookie_secure=False, public_origin=origin, root_path="",
            openai_api_key="", openai_model="", openai_base_url="", pdf_font=find_font(),
        )
        engine = create_engine(
            settings.database_url.get_secret_value(),
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        with engine.begin() as connection:
            config = alembic_config()
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        factory = sessionmaker(engine, expire_on_commit=False)
        prepare(settings, factory, directory, origin + "/v1")
        app = create_app(settings, factory)
        stopping = threading.Event()

        def work():
            while not stopping.is_set():
                if not run_once(factory, settings, provider=diagnosis):
                    stopping.wait(0.1)

        worker = threading.Thread(target=work, name="e2e-worker", daemon=True)
        worker.start()
        try:
            server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
            server.run(sockets=[listener])
        finally:
            stopping.set()
            worker.join(timeout=10)
            engine.dispose()


if __name__ == "__main__":
    main()
