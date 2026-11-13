"""검증된 기준 자료만 제공한다. 자료 부재와 서비스 미지원을 구분한다."""

import copy
import hashlib
import json

from app.contract_data import ENUMS
from app.errors import require

RETAKE_GUIDE = ["동일 부위를 이전 사진과 비슷한 위치·거리·조명에서 촬영하세요.",
                "촬영일을 확인하고 다른 부위는 별도 묶음으로 구분하세요."]


def versions(ctx):
    result = {"regionVersion": None, "travelVersion": None, "durationVersion": None,
              "assumptions": ["이동시간은 사전에 검증한 고정 모의 자료이며 실제 도로 이동시간을 보장하지 않습니다."]}
    for kind, field in (("REGION", "regionVersion"), ("TRAVEL", "travelVersion"), ("DURATION", "durationVersion")):
        records = ctx.references(kind)
        if records:
            result[field] = ",".join(sorted({r.version for r in records}))
    return result


def region(ctx, value):
    if not value:
        return None
    for record in ctx.references("REGION"):
        if all(value.get(k) == record.data.get(k) for k in ("city", "district", "neighborhood")):
            if value.get("regionId") and value["regionId"] != record.id:
                return None
            return {**record.data, "regionId": record.id, "version": record.version}
    return None


def support(ctx, value, facts=None):
    status, reasons, missing = "SUPPORTED", [], []
    if not value:
        status, missing = "INPUT_REQUIRED", ["region"]
    elif value.get("city") not in ("서울특별시", "서울"):
        status, reasons = "UNSUPPORTED_REGION", ["서울특별시 밖의 접수·기록은 가능하지만 서비스 내 예약은 지원하지 않습니다."]
    elif not region(ctx, value):
        status, reasons = "DATA_INCOMPLETE", ["해당 서울 동의 검증된 기준 자료가 필요합니다."]
    if facts is not None and not facts.get("fields"):
        if facts.get("otherField"):
            status, reasons = "UNSUPPORTED_FIELD", ["등록된 5개 분야 밖의 작업입니다."]
        elif status == "SUPPORTED":
            status, missing = "INPUT_REQUIRED", ["facts.fields"]
    return {"status": status, "reasons": reasons, "missingFields": missing,
            "demoDataAvailable": False}


def require_supported(ctx, root, item):
    value = support(ctx, root.data.get("region"), item.data["facts"])
    if value["status"] == "DATA_INCOMPLETE":
        require(False, "REFERENCE_DATA_MISSING", "지원 지역의 기준 자료를 보완해야 합니다.")
    require(value["status"] == "SUPPORTED", "SERVICE_UNSUPPORTED", "추천·예약의 지원 조건을 확인하세요.", 422)


def guidance(ctx, kind="EMERGENCY", product=None):
    product = product or {}
    guides, routes = [], []
    missing = set()
    invalid_sources = False
    if kind == "MANUFACTURER_AS" and not product.get("manufacturer"):
        missing.add("manufacturer")
    for row in ctx.references("GUIDANCE"):
        data = row.data
        if data.get("type") != kind:
            continue
        if data.get("triggerId") and data["triggerId"] != product.get("triggerId"):
            continue
        if any(data.get(k) and product.get(k) and data[k] != product[k] for k in ("manufacturer", "modelName", "productType")):
            continue
        row_missing = {k for k in data.get("requiredFields", []) if not product.get(k)}
        row_missing.update(k for k in ("manufacturer", "modelName", "productType") if data.get(k) and not product.get(k))
        missing.update(row_missing)
        for guide in data.get("guides", []):
            if row_missing or kind == "MANUFACTURER_AS":
                continue
            if not guide["source"].get("verified") or not guide["source"].get("usageBasis"):
                invalid_sources = True
                continue
            value = copy.deepcopy(guide)
            if not value["applicable"]:
                value["steps"] = []
            guides.append(value)
        for route in data.get("routes", []):
            if (row_missing or missing) and route["productSpecific"]:
                continue
            if not route["source"].get("verified") or not route["source"].get("usageBasis"):
                invalid_sources = True
                continue
            routes.append(copy.deepcopy(route))
    if guides and any(g["applicable"] for g in guides):
        guide_status, guide_missing = "AVAILABLE", []
    elif kind == "MANUFACTURER_AS" or guides:
        guide_status, guide_missing = "NOT_APPLICABLE", []
    elif missing:
        guide_status, guide_missing = "INFORMATION_REQUIRED", sorted(missing)
    else:
        guide_status, guide_missing = "VALIDATION_FAILED" if invalid_sources else "NOT_REGISTERED", []
    official_status = "INFORMATION_REQUIRED" if missing else "AVAILABLE" if routes else "VALIDATION_FAILED" if invalid_sources else "NOT_REGISTERED"
    return {"guide": {"status": guide_status, "guides": guides, "missingFields": guide_missing,
                      "message": "등록된 검증 안내입니다." if guides else "제공 가능한 검증 가이드가 없습니다."},
            "officialService": {"status": official_status, "routes": routes,
                                "missingFields": sorted(missing), "message": "등록된 공식 경로입니다." if routes else "공식 경로 제공 조건과 등록 여부를 확인하세요."}}


def service_info(ctx):
    return {"introduction": "고쳐야집: 사진·증상 기록과 선택적인 기사 상담·예약을 지원합니다.",
            "fields": ENUMS["ServiceField"],
            "regions": [{**r.data, "regionId": r.id, "version": r.version} for r in ctx.references("REGION")],
            "referenceVersions": versions(ctx), "emergencyTriggers": [
                {"triggerId": r.id, "label": r.data["label"], "version": r.version} for r in ctx.references("EMERGENCY_TRIGGER")], "retakeGuide": RETAKE_GUIDE}


def verified_source(ctx, source, content=None, case=None):
    candidates = [r for r in ctx.references("SOURCE") if
                  all(r.data.get(k) == source.get(k) for k in ("reference", "title")) and r.version == source.get("version")]
    require(candidates and source.get("usageBasis"), "SOURCE_NOT_VERIFIED", "운영자가 검증한 출처와 사용 근거가 필요합니다.", 422)
    if content is not None:
        digest = hashlib.sha256(content).hexdigest()
        require(any(r.data.get("identifiersRemoved") and digest in r.data.get("assetSha256", []) for r in candidates),
                "SOURCE_NOT_VERIFIED", "출처와 비식별 상태를 확인한 준비 사진만 등록할 수 있습니다.", 422)
    if case is not None:
        value = {k: v for k, v in case.items() if k != "source"}
        digest = hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        require(any(r.data.get("identifiersRemoved") and digest in r.data.get("caseSha256", []) for r in candidates),
                "SOURCE_NOT_VERIFIED", "준비 사례의 내용·비식별 확인이 필요합니다.", 422)
    return {**copy.deepcopy(source), "verifiedAt": candidates[0].data.get("verifiedAt"), "verified": True}


def duration(ctx, item):
    facts = item.data["facts"]
    for row in ctx.references("DURATION"):
        if row.data.get("workType") == facts.get("workType") and row.data.get("quantity") == facts.get("quantity"):
            return {"minutes": row.data["minutes"], "referenceId": row.id, "version": row.version, "technicianConfirmed": False}
    return {"minutes": None, "referenceId": None, "version": None, "technicianConfirmed": False}
