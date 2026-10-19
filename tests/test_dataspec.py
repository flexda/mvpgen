import copy
import json

import pytest
from pydantic import ValidationError

from mvpgen.data_prompts import DATA_SPEC_EXAMPLE
from mvpgen.dataspec import PIPELINE_HEADINGS, DataSpec, check_data_plan


def example() -> dict:
    return copy.deepcopy(DATA_SPEC_EXAMPLE)


def write_plan(run_dir, spec: dict) -> None:
    (run_dir / "context").mkdir(exist_ok=True)
    (run_dir / "context" / "air-api.md").write_text("# API")
    (run_dir / "pipeline.json").write_text(json.dumps(spec, ensure_ascii=False))
    (run_dir / "PIPELINE.md").write_text("\n\n".join(f"{h}\n" + "내용 " * 40 for h in PIPELINE_HEADINGS))


def test_prompt_example_is_valid():
    spec = DataSpec.model_validate(example())
    assert [t.layer for t in spec.tables] == ["raw", "core", "mart"]


@pytest.mark.parametrize("mutate, message", [
    (lambda s: s["tables"][0].update(name="public.pages"), "raw|core|mart"),
    (lambda s: s.update(tables=[t for t in s["tables"] if not t["name"].startswith("core.")]), "core"),
    (lambda s: s["checks"][0].update(sql="delete from core.measurement"), "SELECT"),
    (lambda s: s["intent"][0].update(covered_by=["core.nothing"]), "intent"),
    (lambda s: s["source"].update(key_env="air-key"), "환경변수"),
])
def test_invalid_specs(mutate, message):
    spec = example()
    mutate(spec)
    with pytest.raises(ValidationError, match=message):
        DataSpec.model_validate(spec)


def test_check_data_plan_passes(tmp_path):
    write_plan(tmp_path, example())
    assert check_data_plan(tmp_path, ["AIR_API_KEY"]) == []


def test_check_data_plan_reports_missing_key_and_doc(tmp_path):
    spec = example()
    spec["source"]["doc"] = "context/missing.md"
    write_plan(tmp_path, spec)
    problems = check_data_plan(tmp_path, [])
    assert any("AIR_API_KEY" in p for p in problems)
    assert any("missing.md" in p for p in problems)


def test_check_data_plan_missing_files(tmp_path):
    problems = check_data_plan(tmp_path, [])
    assert "pipeline.json이 없다" in problems and "PIPELINE.md가 없다" in problems


def test_sample_must_match_key_env():
    s = example()
    s["source"]["sample"]["params"]["serviceKey"] = "fixed"
    with pytest.raises(ValidationError, match="\\{key\\}"):
        DataSpec.model_validate(s)
    s = example()
    s["source"]["key_env"] = None
    with pytest.raises(ValidationError, match="key_env가 없는데"):
        DataSpec.model_validate(s)
    s = example()
    s["source"]["sample"]["params"]["date"] = "{today}"
    with pytest.raises(ValidationError, match="today"):
        DataSpec.model_validate(s)
