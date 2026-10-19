import json
from datetime import datetime

import pytest

from mvpgen.pipeline import STAGE_MODEL_KEYS, find_run_dir, make_slug, model_for, name_slug, parse_stage_models


def test_stage_model_keys_follow_stage_table():
    assert STAGE_MODEL_KEYS == ("plan", "design", "build", "critic", "plan-critic", "design-critic", "build-critic")


def test_model_for_resolution():
    m = {"build": "b", "critic": "c", "design-critic": "dc"}
    assert model_for("plan", m, "d") == "d"
    assert model_for("build", m, "d") == "b"
    assert model_for("build-fix2", m, "d") == "b"
    assert model_for("plan-critic", m, "d") == "c"
    assert model_for("design-critic", m, "d") == "dc"
    assert model_for("build-critic", {}, "d") == "d"


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
