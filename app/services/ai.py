"""명시적으로 요청한 AI 작업만 생성하며 결과의 근거 버전을 보존한다."""

import copy
from datetime import timedelta

from app.contracts import validate_type
from app.db import now, uid
from app.errors import require
from app.services import reference, requests, technicians, views
from app.time_rules import as_utc, iso


def target(ctx, root, body):
    kind = body["type"]
    require(("photoGroupId" in body) == (kind == "PHOTO_COMPARISON"), "VALIDATION_ERROR", "사진 묶음은 비교 작업에서만 필수입니다.", 422)
    require(("guideId" in body) == (kind == "GUIDE_EXPLANATION"), "VALIDATION_ERROR", "가이드는 맞춤 설명에서만 필수입니다.", 422)
    if kind == "PHOTO_COMPARISON":
        group = ctx.own(body["photoGroupId"], "PHOTO_GROUP")
        require(group.request_id == root.id and not body.get("workItemId"), "INVALID_REFERENCE", "비교 묶음의 요청을 확인하세요.", 422)
        require(len(group.data["comparisonPhotoIds"]) == 2, "INVALID_COMPARISON_PAIR", "비교할 두 사진을 선택하세요.")
        return root, None
    require(body.get("workItemId"), "VALIDATION_ERROR", "작업 항목을 지정하세요.", 422)
    item = ctx.own(body["workItemId"], "WORK_ITEM")
    require(item.request_id == root.id, "INVALID_REFERENCE", "다른 요청의 항목입니다.", 422)
    if kind == "QUESTION":
        require(not root.data["dialogueFinished"] and len(root.data["questions"]) < 5, "QUESTION_LIMIT_REACHED", "문답이 종료되었거나 5회에 도달했습니다.")
        require(not any(q["answer"] is None and not q["skipped"] for q in root.data["questions"]), "INVALID_STATE", "현재 질문을 먼저 답변하거나 건너뛰세요.")
    if kind == "GUIDE_EXPLANATION":
        guides = reference.guidance(ctx, "SELF_HELP", item.data["facts"]["product"])["guide"]["guides"]
        require(any(g["guideId"] == body["guideId"] and g["applicable"] for g in guides), "GUIDE_NOT_APPLICABLE", "적용 가능한 검증 가이드가 필요합니다.", 422)
    if kind == "CASE_MATCHING":
        reference.require_supported(ctx, root, item)
        require(item.data["reviewStatus"] == "CONFIRMED", "CONFIRMATION_REQUIRED", "요약과 분야를 먼저 확인하세요.")
    return item, item


def create(ctx, root, body):
    ctx.open_request(root)
    source, item = target(ctx, root, body)
    ctx.check_source(source, body["sourceRevision"])
    if body.get("retryOfJobId"):
        old = ctx.own(body["retryOfJobId"], "AI_JOB")
        require(old.request_id == root.id and old.status in ("FAILED", "TIMED_OUT") and
                all(old.data.get(k) == body.get(k) for k in ("type", "workItemId", "photoGroupId", "guideId")),
                "INVALID_STATE", "같은 대상의 실패 작업만 재시도할 수 있습니다.")
    running = [r for r in ctx.find("AI_JOB", request_id=root.id) if r.status in ("QUEUED", "RUNNING") and
               all(r.data.get(k) == body.get(k) for k in ("type", "workItemId", "photoGroupId", "guideId"))]
    require(not running, "AI_JOB_ALREADY_RUNNING", "같은 대상의 AI 작업이 처리 중입니다.")
    deadline = now()+timedelta(seconds=60)
    row = ctx.create("AI_JOB", {"workItemId": None, "photoGroupId": None, "guideId": None, "retryOfJobId": None,
                     **body, "deadlineAt": iso(deadline), "startedAt": None, "finishedAt": None,
                     "attempts": [], "result": None, "error": None}, request_id=root.id,
                     item_id=item.id if item else None, status="QUEUED")
    ctx.enqueue(row, "AI", {"type": body["type"]}, deadline)
    if item:
        ctx.save(item, aiUseStatus="INCOMPLETE")
    return row


def source_current(ctx, row):
    source = ctx.get(row.item_id or row.request_id)
    return source.data["sourceRevision"] == row.data["sourceRevision"]


def view(ctx, row):
    stale = not source_current(ctx, row)
    timed_out = row.status in ("QUEUED", "RUNNING") and as_utc(row.data["deadlineAt"]) <= now()
    error = row.data["error"]
    if timed_out:
        from app.errors import DomainError
        error = DomainError("AI_DEADLINE_EXCEEDED", "접수 후 60초 제한을 초과했습니다.", retryable=True).body()
    return {"jobId": row.id, "type": row.data["type"], "requestId": row.request_id,
            "workItemId": row.item_id, "photoGroupId": row.data["photoGroupId"], "guideId": row.data["guideId"],
            "sourceRevision": row.data["sourceRevision"], "status": "TIMED_OUT" if timed_out else row.status,
            "receivedAt": iso(row.created_at), "startedAt": row.data["startedAt"],
            "finishedAt": row.data["deadlineAt"] if timed_out else row.data["finishedAt"],
            "deadlineAt": row.data["deadlineAt"], "attempts": row.data["attempts"],
            "retryOfJobId": row.data["retryOfJobId"], "stale": stale,
            "result": None if stale or timed_out else row.data["result"], "error": error}


def dialogue(ctx, root, body):
    action = body["action"]
    require(action == "ANSWER" or not any(k in body for k in ("answer", "optionId")), "VALIDATION_ERROR", "답변 액션에만 답변을 전송하세요.", 422)
    questions = copy.deepcopy(root.data["questions"])
    question = next((q for q in questions if q["questionId"] == body.get("questionId")), None)
    if action != "FINISH":
        require(question, "INVALID_REFERENCE", "발행된 질문을 선택하세요.", 422)
        if question["answer"] is not None or question["skipped"]:
            same = (action == "SKIP" and question["skipped"]) or (action == "ANSWER" and
                    question.get("submittedAnswer") == body.get("answer") and question.get("optionId") == body.get("optionId"))
            require(same, "VERSION_CONFLICT", "이미 다른 답변으로 처리했습니다.")
            return views.dialogue(ctx, root)
    else:
        require(not body.get("questionId"), "VALIDATION_ERROR", "종료 시 질문을 지정하지 마세요.", 422)
        if root.data["dialogueFinished"]:
            return views.dialogue(ctx, root)
    require(root.data["dialogueRevision"] == body["expectedRevision"], "VERSION_CONFLICT", "문답이 변경되었습니다.")
    require(not root.data["dialogueFinished"], "INVALID_STATE", "종료한 문답입니다.")
    urgent = root.data["urgent"]
    if action == "ANSWER":
        require(body.get("answer") or body.get("optionId"), "VALIDATION_ERROR", "답변 또는 선택지가 필요합니다.", 422)
        option = next((o for o in question["options"] if o["optionId"] == body.get("optionId")), None)
        require(not body.get("optionId") or option, "INVALID_REFERENCE", "유효한 선택지가 아닙니다.", 422)
        question.update(answer=body.get("answer") or option["label"], submittedAnswer=body.get("answer"), optionId=body.get("optionId"))
        urgent = urgent or bool(option and option.get("triggerId"))
    elif action == "SKIP":
        question["skipped"] = True
    finished = action == "FINISH" or sum(q["answer"] is not None or q["skipped"] for q in questions) >= 5
    ctx.save(root, questions=questions, dialogueFinished=finished, dialogueRevision=uid(), urgent=urgent)
    ctx.invalidate_sources(root)
    return views.dialogue(ctx, root)


def latest_comparisons(ctx, root):
    by_group = {}
    for job in ctx.find("AI_JOB", request_id=root.id):
        if (
            job.data.get("type") == "PHOTO_COMPARISON"
            and job.status == "SUCCEEDED"
            and job.data.get("sourceRevision") == root.data["sourceRevision"]
            and (job.data.get("result") or {}).get("comparison")
        ):
            by_group[job.data["photoGroupId"]] = copy.deepcopy(job.data["result"]["comparison"])
    return list(by_group.values())


def snapshot(ctx, row):
    root = ctx.get(row.request_id, "REQUEST")
    item = ctx.get(row.item_id, "WORK_ITEM") if row.item_id else None
    photos = ctx.find("PHOTO", request_id=root.id)
    if item:
        photos = [p for p in photos if not p.data["workItemIds"] or item.id in p.data["workItemIds"]]
    group = ctx.get(row.data["photoGroupId"]) if row.data["photoGroupId"] else None
    if group:
        photos = [ctx.get(p) for p in group.data["comparisonPhotoIds"]]
    candidates = technicians.candidates(ctx, item) if row.data["type"] == "CASE_MATCHING" else []
    candidate_ids = {c["technician"]["technicianId"] for c in candidates}
    cases = (
        [views.case(ctx, c) for c in ctx.find("CASE") if c.technician_id in candidate_ids]
        if row.data["type"] == "CASE_MATCHING"
        else []
    )
    comparisons = latest_comparisons(ctx, root) if row.data["type"] == "REPORT_DRAFT" else []
    prompt = {"type": row.data["type"], "symptom": root.data["symptom"], "context": root.data["context"],
              "item": views.work_item(ctx, item) if item else None, "dialogue": views.dialogue(ctx, root),
              "photos": [views.photo(ctx, p) for p in photos],
              "records": [views.record(ctx, r) for r in ctx.find("RECORD", request_id=root.id)],
              "performances": [{"reservationId": r.id, "workItemId": r.item_id, "performance": r.data["performance"],
                                "actualStartedAt": r.data["actualStartedAt"], "actualEndedAt": r.data["actualEndedAt"]}
                               for r in ctx.find("RESERVATION", request_id=root.id)
                               if r.status in ("COMPLETED", "STOPPED") and (not item or r.item_id == item.id)],
              "group": group.data | {"groupId": group.id} if group else None,
              "guide": reference.guidance(ctx, "SELF_HELP", item.data["facts"]["product"]) if row.data["guideId"] else None,
              "candidates": candidates,
              "cases": cases,
              "comparisons": comparisons}
    from app.services.handover import scrub_visit_details
    prompt = scrub_visit_details(ctx, root, prompt)
    # Structured and known textual address/contact values are excluded.
    return prompt, [{"photoId": p.id, "bytes": ctx.files.read(ctx.file_for(p).key)} for p in photos]


def accept_result(ctx, row, result):
    validate_type(result, "AiResultDTO", "result", output=True)
    kind = row.data["type"]
    expected = {"DIAGNOSIS": "summary", "QUESTION": "question", "GUIDE_EXPLANATION": "guideExplanation",
                "CASE_MATCHING": "caseRecommendations", "PHOTO_COMPARISON": "comparison", "REPORT_DRAFT": "reportDraft"}[kind]
    require(result.get(expected) is not None, "AI_INVALID_OUTPUT", "필수 AI 결과가 없습니다.")
    item = ctx.get(row.item_id) if row.item_id else None
    for key in ("summary", "reportDraft"):
        if result.get(key):
            requests.validate_facts_references(ctx, item, result[key]["facts"])
            for fact in result[key]["facts"]:
                require(fact["sourceType"] != "FIELD_CONFIRMED", "AI_INVALID_OUTPUT", "AI가 현장 확인 사실을 생성할 수 없습니다.")
    if result.get("reportDraft"):
        ctx.validate_references(result["reportDraft"]["photoIds"], "PHOTO", row.request_id, row.item_id)
    if kind == "QUESTION":
        root = ctx.get(row.request_id)
        require(not root.data["dialogueFinished"] and len(root.data["questions"]) < 5 and
                not any(q["answer"] is None and not q["skipped"] for q in root.data["questions"]),
                "STALE_SOURCE", "문답 상태가 변경되었습니다.")
        question = result["question"]
        question.update(questionId=uid(), answer=None, optionId=None, skipped=False)
        for option in question["options"]:
            option["optionId"] = uid()
            # A model cannot invent an official emergency trigger.
            require(option.get("triggerId") is None or any(r.id == option["triggerId"] for r in ctx.references("EMERGENCY_TRIGGER")),
                    "AI_INVALID_OUTPUT", "미등록 긴급 식별자입니다.")
        ctx.save(root, questions=[*root.data["questions"], question], dialogueRevision=uid())
    if kind == "PHOTO_COMPARISON":
        group = ctx.get(row.data["photoGroupId"])
        comparison = result["comparison"]
        require(comparison["groupId"] == group.id and comparison["photoIds"] == group.data["comparisonPhotoIds"],
                "AI_INVALID_OUTPUT", "비교 대상이 변경되었습니다.")
        comparison["chronologyKnown"] = group.data["chronologyKnown"]
        comparison["causeUnknown"] = True
        if not group.data["chronologyKnown"]:
            comparison["status"] = "INCOMPARABLE"
            comparison["reason"] = "촬영 시간 선후가 확인되지 않아 변화 방향을 판단할 수 없습니다."
        for region in comparison["regions"]:
            photo = ctx.get(region["photoId"], "PHOTO")
            require(photo.id in comparison["photoIds"], "AI_INVALID_OUTPUT", "비교 사진 밖의 영역입니다.")
            file = ctx.file_for(photo)
            require(region["width"] == file.width and region["height"] == file.height, "AI_INVALID_OUTPUT", "원본 사진 크기가 다릅니다.")
    if kind == "CASE_MATCHING":
        available = {c["technician"]["technicianId"]: c for c in technicians.candidates(ctx, item)}
        recommendations = result["caseRecommendations"]
        verified = []
        seen_technicians = set()
        for recommendation in recommendations["recommendations"]:
            tech_id = recommendation["candidate"]["technician"]["technicianId"]
            require(tech_id in available and tech_id not in seen_technicians, "AI_INVALID_OUTPUT", "추천 조건 밖의 기사이거나 중복 기사입니다.")
            seen_technicians.add(tech_id)
            scored = recommendation["cases"]
            require(scored, "AI_INVALID_OUTPUT", "근거 사례가 없습니다.")
            seen = set()
            for evidence in scored:
                case = ctx.get(evidence["case"]["caseId"], "CASE")
                require(case.technician_id == tech_id and case.id not in seen and type(evidence["score"]) is int and
                        1 <= evidence["score"] <= 5 and evidence["evidence"], "AI_INVALID_OUTPUT", "사례 점수·근거가 유효하지 않습니다.")
                seen.add(case.id)
                evidence["case"] = views.case(ctx, case)
            scored = sorted([c for c in scored if c["score"] >= 3], key=lambda c: (-c["score"], c["case"]["caseId"]))[:3]
            if not scored or available[tech_id]["timeFit"] != "MATCHED":
                continue
            recommendation["candidate"] = available[tech_id]
            recommendation["cases"] = scored
            recommendation["averageScore"] = sum(c["score"] for c in scored)/len(scored)
            verified.append(recommendation)
        verified.sort(key=lambda r: (-r["averageScore"], r["candidate"]["technician"]["technicianId"]))
        verified = verified[:5]
        for rank, r in enumerate(verified, 1):
            r["rank"] = rank
        recommendations.update(evaluationStatus="COMPLETED", sourceRevision=row.data["sourceRevision"], stale=False, recommendations=verified)
    if item:
        ctx.save(item, aiUseStatus="COMPLETED")
    return {"summary": None, "fieldCandidates": [], "question": None, "guideExplanation": None,
            "caseRecommendations": None, "comparison": None, "reportDraft": None, **result}
