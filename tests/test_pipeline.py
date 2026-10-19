import json
from datetime import datetime

import pytest

from mvpgen.pipeline import (STAGE_MODEL_KEYS, find_run_dir, make_slug, model_for, name_slug, parse_stage_models,
                             resolve_settings)


def test_stage_model_keys_follow_stage_table():
    assert STAGE_MODEL_KEYS == ("prd", "spec", "design", "build", "plan", "critic",
                                "prd-critic", "spec-critic", "design-critic", "build-critic", "plan-critic")


def test_resolve_settings_reads_legacy_state_and_defaults():
    legacy = {"model": "m0", "stage_models": {"plan": "p"}}
    got = resolve_settings({"model": None, "stage_models": {}, "effort": None, "budget_usd": None, "design": None}, legacy)
    assert got == {"model": "m0", "stage_models": {"plan": "p"}, "effort": "high", "budget_usd": 10.0, "design": "auto",
                   "spec_candidates": 2}
    assert resolve_settings({"effort": "low"}, None)["effort"] == "low"


def test_model_for_resolution():
    m = {"build": "b", "critic": "c", "design-critic": "dc"}
    assert model_for("plan", m, "d") == "d"
    assert model_for("build", m, "d") == "b"
    assert model_for("build-fix2", m, "d") == "b"
    assert model_for("plan-critic", m, "d") == "c"
    assert model_for("design-critic", m, "d") == "dc"
    assert model_for("build-critic", {}, "d") == "d"
    assert model_for("design-directions", {"design": "x"}, "d") == "x"
    # 예전 plan 키는 prd와 spec에 쓰이고, 새 키가 있으면 그것이 우선한다
    legacy = {"plan": "p", "plan-critic": "pc", "critic": "c", "spec": "s"}
    assert [model_for(st, legacy, "d") for st in ("prd", "spec", "prd-critic", "spec-critic", "build-critic")] == [
        "p", "s", "pc", "pc", "c"]


def test_parse_stage_models():
    assert parse_stage_models(["plan=claude-sonnet-5-5", " critic = claude-haiku-5-5 "]) == {
        "plan": "claude-sonnet-5-5", "critic": "claude-haiku-5-5"}
    for bad in (["plan"], ["plan="], ["deploy=x"], ["plan=a", "plan=b"]):
        with pytest.raises(ValueError):
            parse_stage_models(bad)


def test_slug_uses_ascii_words():
    now = datetime(2026, 10, 12, 15, 30, 0)
    assert make_slug("Todo 웹앱 with tags", now) == "20261012-153000-todo-with-tags"
    assert make_slug("할 일 목록 웹앱", now) == "20261012-153000-mvp"


def test_name_slug_keeps_safe_chars():
    assert name_slug("Simple Memo!") == "simple-memo"
    assert name_slug("메모장") == ""
    assert len(name_slug("a" * 100)) == 40


def test_find_run_dir_follows_rename(tmp_path):
    renamed = tmp_path / "20261012-153000-simple-memo"
    renamed.mkdir()
    (renamed / "state.json").write_text(json.dumps({"idea": "x", "renamed_from": "20261012-153000-mvp"}))
    other = tmp_path / "20261012-153000-other"
    other.mkdir()
    (other / "state.json").write_text(json.dumps({"idea": "y"}))

    assert find_run_dir(tmp_path, "20261012-153000-mvp") == renamed
    assert find_run_dir(tmp_path, "20261012-153000-simple-memo") == renamed
    assert find_run_dir(tmp_path, "20261012-160000-mvp") is None
    assert find_run_dir(tmp_path, "20261012-153000-todo-mvp") is None
