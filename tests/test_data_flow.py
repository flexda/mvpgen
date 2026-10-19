"""SDK 호출과 DB 검사를 가짜로 바꿔 데이터 모드 전체 흐름을 오프라인으로 확인한다."""

import json

import mvpgen.pipeline as pipeline_mod
from mvpgen.agents import AgentRun
from mvpgen.datasample import SampleResult
from mvpgen.datapipe import DataPipeline
from mvpgen.pipeline import RunConfig, model_for
from mvpgen.verify import StepResult, VerifyResult
from test_dataspec import example, write_plan


def make_fake_agent(calls, major_always=False):
    async def fake_run_agent(*, stage, cwd, gate=None, prompt="", **kw):
        calls.append((stage, prompt, kw))
        rnd = int(str(kw["log_path"]).rsplit("-r", 1)[1].split(".")[0])
        if stage == "data-plan":
            write_plan(cwd, example())
        elif stage == "data-build":
            (cwd / "app" / "ingest.py").write_text("print('ok')")
            if rnd == 1:
                # 첫 종료 시도는 DB 검사가 실패해 막혀야 한다
                first = await gate({"hook_event_name": "Stop", "stop_hook_active": False}, None, None)
                assert first["decision"] == "block" and "db/check-1.md" in first["reason"]
            assert await gate({"hook_event_name": "Stop", "stop_hook_active": True}, None, None) == {}
        elif stage.endswith("-critic"):
            path = cwd / "reviews" / f"{stage.removesuffix('-critic')}-r{rnd}.json"
            passed = not (stage == "data-build-critic" and (rnd == 1 or major_always))
            # major_always면 critic이 pass와 높은 점수를 줘도 major가 남는다
            review = {"pass": passed or major_always, "score": 90 if passed or major_always else 70, "summary": "평가",
                      "issues": [] if passed else [{"severity": "major", "location": "ingest.py",
                                                    "problem": "timeout이 없다", "fix": "요청에 timeout을 둔다"}]}
            path.write_text(json.dumps(review))
        return AgentRun(stage, True, "success", 0.1, 3, 0.01, gate=gate.stats() if gate else None)

    return fake_run_agent


def make_fake_verifier(calls):
    def verify(app_dir, spec, run_dir, label, page_cap):
        calls.append((label, page_cap))
        ok = label != "check-1"
        (run_dir / "db").mkdir(exist_ok=True)
        (run_dir / "db" / f"{label}.md").write_text(label)
        return VerifyResult([StepResult("idempotency", ok, None, "" if ok else "행 수가 바뀌었다", 0.0)])

    return verify


def fake_sampler(sampled):
    def sample(spec, run_dir, env):
        sampled.append(dict(env))
        d = run_dir / "context" / "samples"
        d.mkdir(parents=True, exist_ok=True)
        (d / "page-1.json").write_text("{}")
        return SampleResult(True, "샘플 1개를 받았다 (API 호출 1회)", 1, ["page-1.json"])

    return sample


def make_pipe(tmp_path, checks, sampled, max_review_rounds=2):
    run_dir = tmp_path / "run"
    (run_dir / "context").mkdir(parents=True)
    (run_dir / "context" / "air-api.md").write_text("# API")
    config = RunConfig(idea="대기질을 매일 적재", out_dir=tmp_path, budget_usd=5, mvp_env={"AIR_API_KEY": "k" * 10},
                       extra_secrets=["dburl-secret"], max_review_rounds=max_review_rounds)
    return run_dir, DataPipeline(config, run_dir, make_fake_verifier(checks), check_pages=2, final_pages=None,
                                 sampler=fake_sampler(sampled))


async def test_data_flow_offline(tmp_path, monkeypatch):
    calls, checks, sampled = [], [], []
    monkeypatch.setattr(pipeline_mod, "run_agent", make_fake_agent(calls))
    run_dir, pipe = make_pipe(tmp_path, checks, sampled)

    assert await pipe.run() is True

    stages = [c[0] for c in calls]
    assert stages == ["data-plan", "data-plan-critic", "data-build", "data-build-critic", "data-build", "data-build-critic"]
    # critic에는 DB 근거 파일이 전달되고, 두 번째 build에는 지적과 직전 근거가 전달되어야 한다
    assert "db/check-2.md" in calls[3][1]
    assert "timeout이 없다" in calls[4][1] and "새 마이그레이션 파일" in calls[4][1]
    # 에이전트 세션에는 API 키를 주지 않고, 키 값은 가드가 막는 비밀값에 들어간다. 샘플은 오케스트레이터가 키로 받는다
    assert all(c[2]["env"] == {} for c in calls)
    assert all(c[2]["extra_secrets"] == ["dburl-secret", "k" * 10] for c in calls)
    assert sampled == [{"AIR_API_KEY": "k" * 10}]
    assert "context/samples/page-1.json" in calls[2][1]
    # 중간 검사는 페이지를 제한하고, 최종 검증만 전체를 받는다
    assert checks[-1] == ("final", None) and all(p == 2 for label, p in checks[:-1])

    report = json.loads((run_dir / "run_report.json").read_text())
    assert report["success"] is True and report["mode"] == "data"
    assert report["api_calls"] == {"samples": 1} and report["open_major"] == {}
    assert report["stages"]["data-build"]["rounds"][1]["rolled_back"] is False
    assert "[data-build] timeout이 없다" in (tmp_path / "lessons.md").read_text()
    assert "supabase db push" in (run_dir / "README.md").read_text()


async def test_open_major_fails_run_even_if_verify_passes(tmp_path, monkeypatch):
    calls, checks, sampled = [], [], []
    monkeypatch.setattr(pipeline_mod, "run_agent", make_fake_agent(calls, major_always=True))
    run_dir, pipe = make_pipe(tmp_path, checks, sampled, max_review_rounds=1)

    assert await pipe.run() is False
    report = json.loads((run_dir / "run_report.json").read_text())
    rounds = report["stages"]["data-build"]["rounds"]
    # critic이 pass와 90점을 줘도 major가 있으면 불합격이고, 개정 한도 뒤에도 남으면 실행은 실패다
    assert [r["accepted"] for r in rounds] == [False, False] and all(r["score"] == 90 for r in rounds)
    assert report["stages"]["data-build"]["status"] == "passed_with_issues"
    assert report["stages"]["verify"]["status"] == "passed"
    assert report["open_major"] == {"data-build": 1}
    assert "major 이슈가 남았다" in (run_dir / "README.md").read_text()


def test_app_mode_acceptance_ignores_major():
    from mvpgen.critic import Review, is_accepted

    review = Review.model_validate({"pass": True, "score": 90, "summary": "s",
                                    "issues": [{"severity": "major", "location": "a", "problem": "p", "fix": "f"}]})
    assert is_accepted(review, 80) is True


def test_fix_sessions_use_build_models():
    models = {"data-build": "sonnet", "build": "opus"}
    assert model_for("data-build-fix2", models, "x") == "sonnet"
    assert model_for("build-fix1", models, "x") == "opus"
    assert model_for("data-plan-critic", {"critic": "c"}, "x") == "c"
