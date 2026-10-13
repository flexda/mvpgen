import json

import pytest
from pydantic import ValidationError

from mvpgen.spec import PRD_HEADINGS, Spec, check_plan


def test_example_spec_is_valid(spec_dict):
    assert Spec.model_validate(spec_dict).name == "quick-notes"


def test_feature_without_criterion_fails(spec_dict):
    spec_dict["features"].append({"id": "F3", "title": "x", "description": "y"})
    with pytest.raises(ValidationError, match="완료 기준이 없는 feature"):
        Spec.model_validate(spec_dict)


def test_criterion_with_unknown_feature_fails(spec_dict):
    spec_dict["acceptance_criteria"].append({"id": "AC9", "feature_id": "F9", "description": "z"})
    with pytest.raises(ValidationError, match="존재하지 않는 feature"):
        Spec.model_validate(spec_dict)


def test_smoke_needs_exactly_one_target(spec_dict):
    spec_dict["smoke"] = {"url": "http://x", "command": "echo", "expect": "a"}
    with pytest.raises(ValidationError):
        Spec.model_validate(spec_dict)


def test_check_plan_reports_missing_files(tmp_path):
    problems = check_plan(tmp_path)
    assert any("spec.json" in p for p in problems)
    assert any("PRD.md" in p for p in problems)


def test_check_plan_passes_complete_plan(tmp_path, spec_dict):
    (tmp_path / "spec.json").write_text(json.dumps(spec_dict))
    body = "\n\n".join(f"{h}\n" + "내용 " * 40 for h in PRD_HEADINGS)
    (tmp_path / "PRD.md").write_text(body)
    assert check_plan(tmp_path) == []


def test_intent_with_unknown_feature_fails(spec_dict):
    spec_dict["intent"].append({"requirement": "공유한다", "feature_ids": ["F9"]})
    with pytest.raises(ValidationError, match="intent가 존재하지 않는 feature"):
        Spec.model_validate(spec_dict)


def test_spec_without_intent_still_loads_but_plan_check_flags_it(tmp_path, spec_dict):
    del spec_dict["intent"]
    assert Spec.model_validate(spec_dict).intent is None
    (tmp_path / "spec.json").write_text(json.dumps(spec_dict))
    (tmp_path / "PRD.md").write_text("\n\n".join(f"{h}\n" + "내용 " * 40 for h in PRD_HEADINGS))
    assert any("intent" in p for p in check_plan(tmp_path))


def test_check_plan_flags_missing_heading(tmp_path, spec_dict):
    (tmp_path / "spec.json").write_text(json.dumps(spec_dict))
    (tmp_path / "PRD.md").write_text("## Problem\n" + "가" * 400)
    assert any("필수 제목" in p for p in check_plan(tmp_path))
