"""DB 기반 작업 큐. AI 외부 호출은 트랜잭션 밖에서 실행한다."""

import copy
import logging
import signal
import time
from datetime import timedelta

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAIError, RateLimitError
from sqlalchemy import or_, select

from app import ai_provider
from app.config import get_settings
from app.db import Job, Resource, StoredFile, lock, now, session_factory, uid
from app.errors import DomainError
from app.observability import configure_logging
from app.pdf import render_pdf
from app.security import Actor
from app.services import ai, deletion, handover, portfolio_analysis
from app.services.context import Context
from app.time_rules import as_utc, iso

logger = logging.getLogger("fmh.worker")
PORTFOLIO_TIMEOUT_SECONDS = 15
CASE_EVALUATION_RESERVE_SECONDS = 30


def context(db, row, settings):
    return Context(db, Actor(row.owner_id, "USER", None, None), settings)


def claim(factory, settings):
    with factory() as db, db.begin():
        lock(db, "worker")
        job = db.scalar(select(Job).where(or_(Job.state == "QUEUED", (Job.state == "RUNNING") & (Job.lease_until < now())))
                        .order_by(Job.created_at, Job.id).limit(1).with_for_update(skip_locked=True))
        if not job:
            return None
        row = db.get(Resource, job.id)
        if not row or row.deleting:
            job.state = "CANCELLED"
            return None
        ctx = context(db, row, settings)
        if job.deadline_at and as_utc(job.deadline_at) <= now():
            row.status, job.state = "TIMED_OUT", "DONE"
            ctx.save(row, finishedAt=iso(now()), error=DomainError("AI_DEADLINE_EXCEEDED", "접수 후 60초 제한을 초과했습니다.", retryable=True).body())
            return None
        token = uid()
        job.state, job.lease_token, job.lease_until = "RUNNING", token, now()+timedelta(seconds=90)
        job.attempts += 1
        row.status = "RUNNING" if job.kind == "AI" else "PROCESSING"
        if job.kind == "AI":
            ctx.save(row, startedAt=row.data["startedAt"] or iso(now()), attempts=[*row.data["attempts"],
                     {"number": job.attempts, "startedAt": iso(now()), "finishedAt": None, "errorCode": None}])
        else:
            ctx.save(row)
        return row.id, token, job.kind


def _portfolio_observations(factory, settings, prompt, deadline):
    if not settings.openai_model or not settings.openai_api_key.get_secret_value():
        return {}
    with factory() as db:
        time_left = (deadline - now()).total_seconds()
        observations, pending = portfolio_analysis.snapshot(
            Context(db, None, settings), prompt,
            analyze_missing=time_left > CASE_EVALUATION_RESERVE_SECONDS,
        )
    timeout = min(
        PORTFOLIO_TIMEOUT_SECONDS,
        (deadline - now()).total_seconds() - CASE_EVALUATION_RESERVE_SECONDS,
    )
    if not pending or timeout <= 0:
        return observations

    try:
        descriptions = ai_provider.describe_portfolio(settings, pending, timeout)
    except (DomainError, OpenAIError) as error:
        logger.warning("portfolio_analysis_failed", extra={"fields": {"errorType": type(error).__name__}})
        return observations

    with factory() as db, db.begin():
        lock(db, "portfolio-analysis-publish")
        ctx = Context(db, None, settings)
        portfolio_analysis.store(ctx, pending, descriptions)
        observations, _ = portfolio_analysis.snapshot(ctx, prompt, analyze_missing=False)
    return observations


def execute(factory, settings, claimed, provider=ai_provider.generate):
    resource_id, token, kind = claimed
    new_files = []
    try:
        if kind in ("AI", "PDF"):
            with factory() as db:
                row, job = db.get(Resource, resource_id), db.get(Job, resource_id)
                ctx = context(db, row, settings)
                if kind == "AI":
                    prompt, photos = ai.snapshot(ctx, row)
                    deadline = as_utc(job.deadline_at)
                    remaining = (deadline-now()).total_seconds()-1
                    if remaining <= 0:
                        raise DomainError("AI_DEADLINE_EXCEEDED", "접수 후 60초 제한을 초과했습니다.")
                else:
                    delivery = ctx.get(job.payload["deliveryId"], "DELIVERY")
                    if not handover.current(ctx, delivery) or str(delivery.revision) != job.payload["deliveryRevision"]:
                        raise DomainError("STALE_SOURCE", "전달본이 변경되었습니다.")
                    content = copy.deepcopy(delivery.data["content"])
                    images = {p["media"]["mediaId"]: ctx.files.read(db.get(StoredFile, p["media"]["mediaId"]).key)
                              for p in content["photos"]}
            if kind == "AI" and prompt["type"] == "CASE_MATCHING":
                prompt["portfolioObservations"] = _portfolio_observations(factory, settings, prompt, deadline)
                remaining = (deadline-now()).total_seconds()-1
                if remaining <= 0:
                    raise DomainError("AI_DEADLINE_EXCEEDED", "접수 후 60초 제한을 초과했습니다.")
            result = provider(settings, prompt, photos, remaining) if kind == "AI" else render_pdf(content, images, settings.pdf_font)
        with factory() as db, db.begin():
            lock(db, "worker-publish")
            row, job = db.get(Resource, resource_id), db.get(Job, resource_id)
            if not row or not job or row.deleting or job.lease_token != token:
                return
            ctx = context(db, row, settings)
            new_files = ctx.new_files
            if row.request_id:
                ctx.get(row.request_id, "REQUEST")
            if kind == "AI":
                if as_utc(job.deadline_at) <= now():
                    raise DomainError("AI_DEADLINE_EXCEEDED", "접수 후 60초 제한을 초과했습니다.")
                if not ai.source_current(ctx, row):
                    raise DomainError("STALE_SOURCE", "실행 중 근거 자료가 변경되었습니다.")
                result = ai.accept_result(ctx, row, result, evaluated_cases=prompt["cases"])
                attempts = copy.deepcopy(row.data["attempts"])
                attempts[-1]["finishedAt"] = iso(now())
                row.status = "SUCCEEDED"
                ctx.save(row, result=result, finishedAt=iso(now()), attempts=attempts, error=None)
                if as_utc(job.deadline_at) <= now():
                    raise DomainError("AI_DEADLINE_EXCEEDED", "결과 저장 중 60초 제한을 초과했습니다.")
            elif kind == "DELIVERY":
                if ctx.get(row.item_id).data["sourceRevision"] != row.data["sourceRevision"]:
                    raise DomainError("STALE_SOURCE", "전달본 근거가 변경되었습니다.")
                handover.render(ctx, row, job.payload)
            elif kind == "PDF":
                delivery = ctx.get(row.parent_id)
                if not handover.current(ctx, delivery) or str(delivery.revision) != row.data["deliveryRevision"]:
                    raise DomainError("STALE_SOURCE", "전달본이 변경되었습니다.")
                ctx.store_file(row, result, "application/pdf")
                row.status = "READY"
                ctx.save(row, completedAt=iso(now()), error=None)
            else:
                deletion.finish(ctx, row, job.payload)
            job.state, job.lease_token, job.lease_until = "DONE", None, None
    except Exception as error:
        from app.media import FileStore
        for key in new_files:
            FileStore(settings.storage_dir).delete(key)
        fail(factory, settings, claimed, error)


def fail(factory, settings, claimed, error):
    resource_id, token, kind = claimed
    transient = isinstance(error, (APIConnectionError, APITimeoutError, RateLimitError)) or (
        isinstance(error, APIStatusError) and error.status_code >= 500)
    with factory() as db, db.begin():
        lock(db, "worker-error")
        row, job = db.get(Resource, resource_id), db.get(Job, resource_id)
        if not row or not job or row.deleting or job.lease_token != token:
            return
        ctx = context(db, row, settings)
        expired = bool(job.deadline_at and as_utc(job.deadline_at) <= now())
        if isinstance(error, DomainError):
            failure = error
        else:
            failure = DomainError("AI_PROVIDER_UNAVAILABLE" if kind == "AI" else "PROCESSING_FAILED",
                                  "처리에 실패했습니다. 설정과 작업 상태를 확인하세요.", retryable=transient or kind != "AI")
        if expired or failure.code == "AI_DEADLINE_EXCEEDED":
            failure = DomainError("AI_DEADLINE_EXCEEDED", "접수 후 60초 제한을 초과했습니다.", retryable=True)
            expired = True
        values = {"error": failure.body()}
        if kind == "AI":
            attempts = copy.deepcopy(row.data["attempts"])
            if attempts:
                attempts[-1].update(finishedAt=iso(now()), errorCode=failure.code)
            values.update(attempts=attempts, finishedAt=iso(now()))
        if transient and kind == "AI" and job.attempts < 2 and not expired and (as_utc(job.deadline_at)-now()).total_seconds() > 2:
            row.status, job.state = "QUEUED", "QUEUED"
            values["finishedAt"] = None
        else:
            row.status = "TIMED_OUT" if expired else "STALE" if kind != "AI" and failure.code == "STALE_SOURCE" else "FAILED"
            job.state = "DONE"
            if row.kind == "FILE_CLEANUP" and job.attempts < 3:
                row.status, job.state = "QUEUED", "QUEUED"
        job.lease_token = job.lease_until = None
        ctx.save(row, **values)
        logger.warning("job_failed", extra={"fields": {"jobId": row.id, "code": failure.code, "errorType": type(error).__name__}})


def run_once(factory=None, settings=None, provider=ai_provider.generate):
    settings, factory = settings or get_settings(), factory or session_factory()
    claimed = claim(factory, settings)
    if claimed:
        execute(factory, settings, claimed, provider)
    return claimed is not None


def main():
    from app.runtime import validate_runtime
    validate_runtime()
    settings = get_settings()
    configure_logging(settings, "worker")
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        if not run_once():
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
