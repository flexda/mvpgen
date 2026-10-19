import json

import pytest
from pydantic import ValidationError

from mvpgen.spec import PRD_HEADINGS, Spec, candidate_spec, check_prd, check_spec, check_spec_candidates


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


def test_check_prd_and_spec_report_missing_files(tmp_path):
    assert check_prd(tmp_path) == ["PRD.md가 없다"]
    assert check_spec(tmp_path) == ["spec.json이 없다"]


def test_check_prd_and_spec_pass(tmp_path, spec_dict):
    (tmp_path / "spec.json").write_text(json.dumps(spec_dict))
    (tmp_path / "PRD.md").write_text("\n\n".join(f"{h}\n" + "내용 " * 40 for h in PRD_HEADINGS))
    assert check_prd(tmp_path) == [] and check_spec(tmp_path) == []


def test_intent_with_unknown_feature_fails(spec_dict):
    spec_dict["intent"].append({"requirement": "공유한다", "feature_ids": ["F9"]})
    with pytest.raises(ValidationError, match="intent가 존재하지 않는 feature"):
        Spec.model_validate(spec_dict)


def test_spec_without_intent_still_loads_but_check_flags_it(tmp_path, spec_dict):
    del spec_dict["intent"]
    assert Spec.model_validate(spec_dict).intent is None
    (tmp_path / "spec.json").write_text(json.dumps(spec_dict))
    assert any("intent" in p for p in check_spec(tmp_path))


def test_check_prd_flags_missing_heading(tmp_path):
    (tmp_path / "PRD.md").write_text("## Problem\n" + "가" * 400)
    assert any("필수 제목" in p for p in check_prd(tmp_path))


def write_candidates(cand_dir, spec_dict, approaches=("API 실시간", "수집 CSV")):
    cand_dir.mkdir(exist_ok=True)
    for cid, approach in zip("abc", approaches):
        (cand_dir / f"{cid}.json").write_text(json.dumps({"decision": "데이터 출처", "approach": approach, "spec": spec_dict}))


def test_spec_candidates_pass_and_winner_spec_is_extracted(tmp_path, spec_dict):
    cand = tmp_path / "spec-candidates"
    write_candidates(cand, spec_dict)
    assert check_spec_candidates(cand, 2) == []
    assert candidate_spec(cand, "b")["name"] == "quick-notes"


def test_spec_candidates_count_and_same_approach(tmp_path, spec_dict):
    cand = tmp_path / "spec-candidates"
    write_candidates(cand, spec_dict, approaches=("같음", "같음"))
    assert any("3개" in p for p in check_spec_candidates(cand, 3))
    assert any("approach가 서로 같다" in p for p in check_spec_candidates(cand, 2))


def test_spec_candidates_need_same_features(tmp_path, spec_dict):
    cand = tmp_path / "spec-candidates"
    write_candidates(cand, spec_dict)
    data = json.loads((cand / "b.json").read_text())
    data["spec"]["features"].append({"id": "F3", "title": "공유", "description": "링크로 공유"})
    data["spec"]["acceptance_criteria"].append({"id": "AC3", "feature_id": "F3", "description": "링크"})
    (cand / "b.json").write_text(json.dumps(data))
    assert any("feature id가 다르다" in p for p in check_spec_candidates(cand, 2))


def test_spec_candidate_schema_error_names_the_file(tmp_path, spec_dict):
    cand = tmp_path / "spec-candidates"
    write_candidates(cand, spec_dict)
    data = json.loads((cand / "a.json").read_text())
    del data["spec"]["run_cmd"], data["decision"]
    (cand / "a.json").write_text(json.dumps(data))
    problems = check_spec_candidates(cand, 2)
    assert any("spec-candidates/a.json에 decision" in p for p in problems)
    assert any("spec-candidates/a.json의 spec 스키마 오류" in p for p in problems)
