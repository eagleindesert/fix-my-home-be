"""등록된 수리 사례에서 AI 호출 없이 비교할 근거를 찾는다."""

import re

from app.services import reference, scheduling, technicians, views


CASE_WORD = re.compile(r"[가-힣a-z0-9]{2,}")
GENERIC_WORDS = {"모의", "사례", "수리", "작업", "교체", "점검", "확인", "필요"}
MAX_REFERENCE_CASES = 5


def _words(*texts):
    return set(CASE_WORD.findall(" ".join(filter(None, texts)).casefold())) - GENERIC_WORDS


def _reference_candidate(ctx, item, technician, region, *, can_check_visit):
    fields = set(item.data["facts"]["fields"])
    matched_fields = fields.intersection(technician.data["profile"]["fields"])
    time_fit = "UNKNOWN"
    if region and region["regionId"] not in technician.data["profile"]["regionIds"]:
        reason = "요청 지역이 이 기사의 서비스 지역에 포함되지 않아요."
    elif fields and not matched_fields:
        reason = "기사 프로필에서 요청한 수리 분야를 확인할 수 없어요."
    elif can_check_visit and matched_fields:
        time_fit, _, reason = scheduling.candidate_fit(ctx, item, technician)
    else:
        reason = "방문 조건을 확인해야 해요."
    return technicians.candidate_view(ctx, item, technician, matched_fields, time_fit=time_fit, reason=reason)


def fallback_recommendations(ctx, root, item):
    cases = ctx.find("CASE")
    if not cases:
        return []

    facts = item.data["facts"]
    fields = set(facts["fields"])
    region = reference.region(ctx, root.data.get("region"))
    can_check_visit = (
        root.status == "OPEN" and item.data["reviewStatus"] == "CONFIRMED"
        and reference.support(ctx, root.data.get("region"), facts)["status"] == "SUPPORTED"
    )
    request_words = _words(
        root.data["symptom"], (item.data.get("summary") or {}).get("text"),
        facts.get("part"), facts.get("workType"),
    )
    technician_by_id = {
        row.id: row for row in ctx.find("TECHNICIAN") if row.owner_id != root.owner_id
    }
    ranked = []
    for row in cases:
        technician = technician_by_id.get(row.technician_id)
        if technician is None:
            continue

        content = row.data["case"]
        same_region = region is not None and region["regionId"] in technician.data["profile"]["regionIds"]
        same_field = bool(fields.intersection(content["fields"]))
        shared_words = request_words & _words(content["title"], content["initialSymptom"], *content["parts"])
        evidence = ["등록 사례 참고 점수예요. 수리 분야와 증상 표현의 일치 여부로 계산했어요."]
        if same_field:
            evidence.append("요청한 수리 분야의 등록 사례예요.")
        if shared_words:
            keywords = ", ".join(sorted(shared_words)[:3])
            evidence.append(f"요청과 등록 사례에서 ‘{keywords}’ 표현이 겹쳐요.")
        if same_field or shared_words:
            priority = 0
        elif same_region:
            priority = 1
            evidence.append("요청 지역을 담당하는 기사의 등록 사례예요.")
        else:
            priority = 2
        score = 1 + int(same_field) + min(len(shared_words), 3)
        key = (priority, -score, not same_region, technician.id, row.id)
        ranked.append((key, technician, row, score, evidence))

    if not ranked:
        return []
    ranked.sort(key=lambda entry: entry[0])
    best_key, *_ = ranked[0]
    results, seen_technicians = [], set()
    conflicting_reference = None
    for key, technician, row, score, evidence in ranked:
        if key[0] != best_key[0] or len(results) == MAX_REFERENCE_CASES:
            break
        if technician.id in seen_technicians:
            continue
        seen_technicians.add(technician.id)
        candidate = _reference_candidate(ctx, item, technician, region, can_check_visit=can_check_visit)
        recommendation = {
            "candidate": candidate,
            "cases": [{"case": views.case(ctx, row), "score": score, "evidence": evidence}],
            "averageScore": float(score),
            "rank": len(results) + 1,
        }
        if candidate["timeFit"] == "NOT_MATCHED":
            if conflicting_reference is None:
                conflicting_reference = recommendation
            continue
        results.append(recommendation)
    return results or ([conflicting_reference] if conflicting_reference else [])
