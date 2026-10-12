from datetime import datetime

from mvpgen.pipeline import make_slug


def test_slug_uses_ascii_words():
    now = datetime(2026, 10, 12, 15, 30, 0)
    assert make_slug("Todo 웹앱 with tags", now) == "20261012-153000-todo-with-tags"
    assert make_slug("할 일 목록 웹앱", now) == "20261012-153000-mvp"
