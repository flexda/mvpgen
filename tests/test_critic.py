import json

from mvpgen.critic import Review, RoundTracker, check_review_file, is_accepted, load_review
from mvpgen.lessons import lessons_prompt, merge_lessons, record_lessons


def review(score, passed=True, issues=()):
    return Review.model_validate({"pass": passed, "score": score, "summary": "s", "issues": list(issues)})


ISSUE = {"severity": "major", "location": "app/main.py", "problem": "삭제 버튼이 동작하지 않는다", "fix": "DELETE 라우트 추가"}
CRIT = {**ISSUE, "severity": "critical"}


def test_review_file_check(tmp_path):
    p = tmp_path / "r.json"
    assert not check_review_file(p)[0]
    p.write_text('{"pass": true}')
    assert "스키마 오류" in check_review_file(p)[1]
    p.write_text(json.dumps({"pass": False, "score": 55, "summary": "부족", "issues": [ISSUE]}))
    assert check_review_file(p)[0]
    assert load_review(p).issues[0].location == "app/main.py"


def test_acceptance_rules():
    assert is_accepted(review(85), 80)
    assert not is_accepted(review(79), 80)
    assert not is_accepted(review(95, passed=False), 80)
    assert not is_accepted(review(95, issues=[CRIT]), 80)


def test_feedback_lists_issues():
    text = review(60, False, [ISSUE]).feedback()
    assert "삭제 버튼" in text and "DELETE 라우트" in text


def test_tracker_rolls_back_on_score_drop(tmp_path):
    root = tmp_path
    app = root / "app"
    app.mkdir()
    (app / "main.py").write_text("v1")
    (app / "node_modules").mkdir()
    (app / "node_modules" / "keep.js").write_text("dep")
    tracker = RoundTracker([app], root, root / "snapshots")

    assert tracker.record(1, review(70, False)) is False
    assert not (root / "snapshots" / "round-1" / "app" / "node_modules").exists()

    (app / "main.py").write_text("v2-worse")
    (app / "extra.py").write_text("new")
    assert tracker.record(2, review(50, False)) is True
    assert (app / "main.py").read_text() == "v1"
    assert not (app / "extra.py").exists()
    assert (app / "node_modules" / "keep.js").exists()
    assert tracker.best.round == 1

    (app / "main.py").write_text("v3-better")
    assert tracker.record(3, review(90)) is False
    assert tracker.best.round == 3


def test_tracker_handles_files(tmp_path):
    prd = tmp_path / "PRD.md"
    prd.write_text("good")
    tracker = RoundTracker([prd], tmp_path, tmp_path / "snaps")
    tracker.record(1, review(80))
    prd.write_text("bad")
    tracker.restore_best()
    assert prd.read_text() == "good"


def test_lessons_dedupe_and_inject(tmp_path):
    path = tmp_path / "lessons.md"
    minor = {**ISSUE, "severity": "minor", "problem": "여백"}
    issues = review(60, False, [ISSUE, minor]).issues
    assert record_lessons(path, "build", issues) == 1
    assert record_lessons(path, "build", issues) == 0
    assert "삭제 버튼" in lessons_prompt(path, "build")
    assert lessons_prompt(path, "plan") == ""


def test_merge_lessons_keeps_both_sides(tmp_path):
    header = "# 이전 실행에서 critic이 지적한 문제\n\n"
    dst = tmp_path / "main.md"
    src = tmp_path / "run.md"
    # main에는 실행 중에 다른 항목(B)이 추가됐고, 실행은 A에 C를 더했다
    dst.write_text(header + "- [plan] A -> a\n- [build] B -> b\n")
    src.write_text(header + "- [plan] A -> a\n- [plan] C -> c\n- [plan] C -> c\n")
    assert merge_lessons(dst, src) == 1
    assert dst.read_text().splitlines()[2:] == ["- [plan] A -> a", "- [build] B -> b", "- [plan] C -> c"]
    assert merge_lessons(dst, src) == 0


def test_merge_lessons_creates_missing_dst(tmp_path):
    src = tmp_path / "run.md"
    src.write_text("# h\n\n- [build] X -> x\n")
    dst = tmp_path / "new" / "lessons.md"
    assert merge_lessons(dst, src) == 1
    assert "- [build] X -> x" in dst.read_text()
