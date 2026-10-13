import json
from datetime import datetime

from mvpgen.pipeline import find_run_dir, make_slug, name_slug


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
