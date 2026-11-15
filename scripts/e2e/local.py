"""임시 SQLite DB와 실제 HTTP 서버/worker를 함께 실행한다. AI만 고정 응답이다."""

import argparse
import os
import socket
import threading
from pathlib import Path

import uvicorn
from alembic import command
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.main import create_app
from app.schema import alembic_config
from app.worker import run_once
from scripts.e2e.fixtures import prepare


def diagnosis(*_):
    return {
        "summary": {
            "text": "E2E 가상 관찰입니다. 원인은 현장 점검이 필요합니다.",
            "facts": [], "unknowns": ["누수 원인"], "riskSignals": [],
            "limitations": ["E2E 고정 응답"], "onsiteInspectionNeeded": True,
        },
        "fieldCandidates": ["PLUMBING"], "question": None, "guideExplanation": None,
        "caseRecommendations": None, "comparison": None, "reportDraft": None,
    }


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
