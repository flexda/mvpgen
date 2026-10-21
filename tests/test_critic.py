import json

from mvpgen.critic import Review, RoundTracker, check_review_file, check_screening_file, is_accepted, load_review
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


def test_screening_file_needs_one_verdict_per_candidate_and_viable_recommendation(tmp_path):
    path = tmp_path / "spec-screen-r1.json"
    verdict = {"viable": True, "score": 80, "summary": "s"}

    def write(candidates, recommended):
        path.write_text(json.dumps({"summary": "s", "candidates": candidates, "recommended": recommended}))

    write([{"id": "a", **verdict}, {"id": "b", **verdict, "viable": False}], "a")
    assert check_screening_file(path, ["a", "b"])[0]
    write([{"id": "a", **verdict}], "a")
    assert "후보마다 하나씩" in check_screening_file(path, ["a", "b"])[1]
    write([{"id": "a", **verdict}, {"id": "b", **verdict, "viable": False}], "b")
    assert "viable 후보 중 하나" in check_screening_file(path, ["a", "b"])[1]
    # viable이 하나도 없어도 형식은 통과다. 다시 만들지는 파이프라인이 정한다
    write([{"id": "a", **verdict, "viable": False}], "a")
    assert check_screening_file(path, ["a"])[0]


def test_verdict_clean_needs_viable_threshold_and_no_critical():
    from mvpgen.critic import Verdict

    assert Verdict(id="a", viable=True, score=85, summary="s").clean(80)
    assert not Verdict(id="a", viable=True, score=75, summary="s").clean(80)
    assert not Verdict(id="a", viable=True, score=95, summary="s", issues=[CRIT]).clean(80)
    assert not Verdict(id="a", viable=False, score=95, summary="s").clean(80)


def test_lessons_prompt_reads_several_stage_names(tmp_path):
    path = tmp_path / "lessons.md"
    path.write_text("# h\n\n- [plan] 예전 지적 -> 고쳐라\n- [spec] 새 지적 -> 고쳐라\n- [build] 다른 단계 -> x\n")
    got = lessons_prompt(path, "spec", "plan")
    assert "예전 지적" in got and "새 지적" in got and "다른 단계" not in got


def test_rank_prefers_round_without_blocking_issue(tmp_path):
    from mvpgen.critic import Review, RoundTracker

    prd = tmp_path / "PRD.md"
    tracker = RoundTracker([prd], tmp_path, tmp_path / "snaps",
                           rank=lambda r: (not any(i.severity == "major" for i in r.issues), r.score))
    major = {"severity": "major", "location": "a", "problem": "p", "fix": "f"}
    prd.write_text("r1 major")
    assert tracker.record(1, Review.model_validate({"pass": True, "score": 90, "summary": "s", "issues": [major]})) is False
    prd.write_text("r2 fixed")
    # 점수는 낮아도 major를 고친 라운드는 되돌리지 않는다
    assert tracker.record(2, Review.model_validate({"pass": False, "score": 78, "summary": "s"})) is False
    assert prd.read_text() == "r2 fixed" and tracker.best.round == 2
    prd.write_text("r3 major again")
    assert tracker.record(3, Review.model_validate({"pass": True, "score": 95, "summary": "s", "issues": [major]})) is True
    assert prd.read_text() == "r2 fixed"
