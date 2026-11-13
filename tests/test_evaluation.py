import json

import pytest

from scripts.evaluate_ai import GROUPS, THRESHOLDS, load_frozen, prepare, report, validate_manifest, write_json


def manifest():
    return {"version": "UNIT-TEST-ONLY", "rubricVersion": "test", "model": "not-a-real-model",
            "cases": [{"id": f"{group}-{i}", "group": group, "input": {}, "expected": {}, "requiredOutput": [],
                       "allowedAnswers": [], "rubric": "UNIT TEST", "metrics": {name: {"units": 1} for name in THRESHOLDS},
                       "provenance": {"kind": "MOCK", "source": "unit test", "usageBasis": "authored test fixture",
                                      "identifiersRemoved": True, "reviewedBy": "test"}}
                      for group in GROUPS for i in range(10)],
            "injections": [{"id": "guide", "kind": "GUIDE", "caseId": "self_help-0", "output": {}, "expectedCritical": True},
                           {"id": "photo", "kind": "PHOTO", "caseId": "photo_comparison-0", "output": {}, "expectedCritical": False}]}


def test_evaluation_rejects_incomplete_groups_and_modified_frozen_input(tmp_path):
    value = manifest()
    value["cases"].pop()
    with pytest.raises(ValueError, match="최소 10"):
        validate_manifest(value)
    source = tmp_path / "manifest.json"
    write_json(source, manifest())
    output = tmp_path / "results"
    prepare(source, output)
    frozen = load_frozen(output)
    frozen["manifest"]["model"] = "changed"
    write_json(output / "frozen.json", frozen)
    with pytest.raises(ValueError, match="변경"):
        load_frozen(output)


def test_no_output_is_failure_and_missing_human_review_never_passes(tmp_path):
    source = tmp_path / "manifest.json"
    write_json(source, manifest())
    output = tmp_path / "results"
    prepare(source, output)
    frozen = load_frozen(output)
    runs = output / "runs"
    runs.mkdir()
    for case in frozen["manifest"]["cases"]:
        for repeat in range(1, 4):
            write_json(runs / f"{case['id']}-{repeat}.json", {"caseId": case["id"], "group": case["group"],
                       "repetition": repeat, "output": None, "evaluation": None, "injected": False, "frozenHash": frozen["sha256"]})
    summary = report(output)
    assert summary["status"] == "INCOMPLETE_OR_FAILED"
    assert summary["metrics"]["field_accuracy"]["value"] == 0
    assert summary["metrics"]["relevance_rating"]["value"] == 1
    assert summary["metrics"]["unsupported_claims"]["value"] is None
    assert all(group["humanRequired"] == 6 and group["noOutputFailures"] == 30 for group in summary["groups"].values())
