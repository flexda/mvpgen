"""SDK 호출을 가짜 에이전트로 바꿔 전체 흐름(Stop gate, critic 개정, 최종 검증)을 오프라인으로 확인한다."""

import json
import sys

import mvpgen.pipeline as pipeline_mod
from mvpgen.agents import AgentRun
from mvpgen.pipeline import Pipeline, RunConfig
from mvpgen.design import DESIGN_HEADINGS
from mvpgen.spec import PRD_HEADINGS

PY = sys.executable
SERVER = (
    "import os, http.server\n"
    "class H(http.server.BaseHTTPRequestHandler):\n"
    "    def do_GET(self):\n"
    "        self.send_response(200); self.end_headers(); self.wfile.write(b'Fake Todo')\n"
    "    def log_message(self, *a): pass\n"
    "http.server.HTTPServer(('127.0.0.1', int(os.environ['PORT'])), H).serve_forever()\n"
)


DESIGN_MD = '---\ncolors:\n  ink: "#111111"\n---\n\n' + "\n\n".join(f"{h}\n" + "내용 " * 120 for h in DESIGN_HEADINGS)


def make_library(root, n=5):
    for i in range(n):
        (root / f"brand{i}").mkdir(parents=True)
        (root / f"brand{i}" / "DESIGN.md").write_text(f"# brand{i}")
    return root


def fake_spec():
    return {
        "name": "fake-todo", "summary": "할 일 목록", "stack": "Python stdlib",
        "intent": [{"requirement": "할 일 목록을 본다", "feature_ids": ["F1"]}],
        "features": [{"id": "F1", "title": "목록", "description": "할 일을 본다"}],
        "acceptance_criteria": [{"id": "AC1", "feature_id": "F1", "description": "GET /에 Fake Todo"}],
        "install_cmd": None, "test_cmd": "test -f ok.txt", "run_cmd": f"{PY} server.py",
        "smoke": {"url": "http://127.0.0.1:{port}/", "expect": "Fake Todo"}, "startup_timeout": 15,
    }


def make_fake_agent(calls):
    async def fake_run_agent(*, stage, cwd, gate=None, prompt="", **kw):
        calls.append((stage, prompt))
        rnd = int(str(kw["log_path"]).rsplit("-r", 1)[1].split(".")[0])
        if stage == "plan":
            (cwd / "spec.json").write_text(json.dumps(fake_spec()))
            (cwd / "PRD.md").write_text("\n\n".join(f"{h}\n" + "내용 " * 40 for h in PRD_HEADINGS))
        elif stage == "design-directions":
            # 첫 종료 시도: 산출물이 없어 gate가 막아야 한다
            first = await gate({"hook_event_name": "Stop", "stop_hook_active": False}, None, None)
            assert first["decision"] == "block" and "concepts.json" in first["reason"]
            cands = sorted(p.stem for p in (cwd / "design-candidates").glob("*.md"))
            dirs = [{"id": i, "kind": k, "sources": [cands[n]], "metaphor": "m", "first_screen": "f", "risks": "r"}
                    for n, (i, k) in enumerate([("A", "baseline"), ("B", "unexpected"), ("C", "unexpected")])]
            (cwd / "concepts.json").write_text(json.dumps({"directions": dirs}))
            assert await gate({"hook_event_name": "Stop", "stop_hook_active": True}, None, None) == {}
        elif stage == "design":
            first = await gate({"hook_event_name": "Stop", "stop_hook_active": False}, None, None)
            assert first["decision"] == "block" and "DESIGN.md" in first["reason"]
            (cwd / "DESIGN.md").write_text(DESIGN_MD)
            assert await gate({"hook_event_name": "Stop", "stop_hook_active": True}, None, None) == {}
        elif stage == "build":
            app = cwd / "app"
            (app / "server.py").write_text(SERVER)
            # 첫 종료 시도: 테스트 파일이 없어 gate가 막아야 한다
            first = await gate({"hook_event_name": "Stop", "stop_hook_active": False}, None, None)
            assert first["decision"] == "block" and "test" in first["reason"]
            (app / "ok.txt").write_text("fixed")
            assert await gate({"hook_event_name": "Stop", "stop_hook_active": True}, None, None) == {}
        elif stage.endswith("-critic"):
            path = cwd / "reviews" / f"{stage.removesuffix('-critic')}-r{rnd}.json"
            passed = not (stage == "plan-critic" and rnd == 1)
            review = {"pass": passed, "score": 90 if passed else 60, "summary": "평가",
                      "issues": [] if passed else [{"severity": "major", "location": "PRD.md",
                                                    "problem": "범위가 넓다", "fix": "기능을 줄여라"}]}
            path.write_text(json.dumps(review))
            ok, _ = gate.checker()
            assert ok
        return AgentRun(stage, True, "success", 0.1, 3, 0.01, gate=gate.stats() if gate else None)

    return fake_run_agent


async def test_full_flow_offline(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline_mod, "run_agent", make_fake_agent(calls))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config = RunConfig(idea="할 일 목록", out_dir=tmp_path, budget_usd=5)

    assert await Pipeline(config, run_dir).run() is True

    stages = [c[0] for c in calls]
    assert stages == ["plan", "plan-critic", "plan", "plan-critic", "build", "build-critic"]
    # 두 번째 plan 호출에는 critic 지적이 전달되어야 한다
    assert "범위가 넓다" in calls[2][1]

    report = json.loads((run_dir / "run_report.json").read_text())
    assert report["success"] is True
    assert [r["score"] for r in report["stages"]["plan"]["rounds"]] == [60, 90]
    assert report["stages"]["build"]["status"] == "passed"
    assert report["stages"]["verify"]["status"] == "passed"
    build_run = next(r for r in report["runs"] if r["stage"] == "build")
    assert build_run["gate"]["blocks"] == 1
    assert abs(report["cost_usd"] - 0.6) < 1e-9
    assert "범위가 넓다" in (tmp_path / "lessons.md").read_text()
    readme = (run_dir / "README.md").read_text()
    assert "fake-todo" in readme and "export PORT=8000" in readme


async def test_lessons_path_outside_out_dir(tmp_path, monkeypatch):
    systems = []
    base = make_fake_agent([])

    async def capture(**kw):
        systems.append((kw["stage"], kw.get("system_prompt", "")))
        return await base(**kw)

    monkeypatch.setattr(pipeline_mod, "run_agent", capture)
    lessons = tmp_path / "repo" / "lessons.md"
    lessons.parent.mkdir()
    lessons.write_text("# h\n\n- [plan] 이전 실행의 기획 지적 -> 고쳐라\n")
    out = tmp_path / "workspace"
    run_dir = out / "run"
    run_dir.mkdir(parents=True)
    config = RunConfig(idea="할 일 목록", out_dir=out, budget_usd=5, lessons_path=lessons)

    assert await Pipeline(config, run_dir).run() is True

    # 저장소의 교훈이 Plan 시스템 프롬프트에 들어가고, 새 지적도 같은 파일에 쌓여야 한다
    assert "이전 실행의 기획 지적" in next(s for st, s in systems if st == "plan")
    assert "범위가 넓다" in lessons.read_text()
    assert not (out / "lessons.md").exists()


async def test_fallback_folder_renamed_after_plan(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline_mod, "run_agent", make_fake_agent(calls))
    old_dir = tmp_path / "20261012-153000-mvp"
    old_dir.mkdir()
    pipe = Pipeline(RunConfig(idea="할 일 목록", out_dir=tmp_path, budget_usd=5), old_dir)

    assert await pipe.run() is True

    new_dir = tmp_path / "20261012-153000-fake-todo"
    assert not old_dir.exists() and pipe.run_dir == new_dir
    # Build 이후 산출물이 모두 새 폴더에 있어야 추적이 이어진다
    assert (new_dir / "app" / "server.py").exists()
    assert (new_dir / "reviews" / "build-r1.json").exists()
    assert (new_dir / "snapshots" / "plan").is_dir() and (new_dir / "snapshots" / "build").is_dir()
    report = json.loads((new_dir / "run_report.json").read_text())
    assert report["renamed_from"] == "20261012-153000-mvp"
    assert report["run_dir"] == "20261012-153000-fake-todo"
    assert report["stages"]["verify"]["status"] == "passed"
    assert pipeline_mod.find_run_dir(tmp_path, "20261012-153000-mvp") == new_dir


async def test_brief_reaches_plan_and_critics(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline_mod, "run_agent", make_fake_agent(calls))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "brief.md").write_text("# 할 일 목록\n- 하지 않을 것: 로그인")

    assert await Pipeline(RunConfig(idea="할 일 목록", out_dir=tmp_path, budget_usd=5), run_dir).run() is True
    for stage in ("plan", "plan-critic", "build-critic"):
        assert "# 요구 원문 (brief.md)" in next(p for s, p in calls if s == stage), stage
    assert json.loads((run_dir / "run_report.json").read_text())["brief"] == "brief.md"


async def test_no_brief_keeps_idea_only_prompts(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline_mod, "run_agent", make_fake_agent(calls))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    assert await Pipeline(RunConfig(idea="할 일 목록", out_dir=tmp_path, budget_usd=5), run_dir).run() is True
    assert not any("brief.md" in p for _, p in calls)


async def test_context_reaches_plan_build_and_critic_after_rename(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline_mod, "run_agent", make_fake_agent(calls))
    run_dir = tmp_path / "20261013-090000-mvp"
    (run_dir / "context").mkdir(parents=True)
    (run_dir / "context" / "exhibitions.csv").write_text("title\nA\n")

    pipe = Pipeline(RunConfig(idea="오늘 뭐하지", out_dir=tmp_path, budget_usd=5), run_dir)
    assert await pipe.run() is True

    # 이름이 바뀐 뒤 Build 단계에도 자료 목록이 전달되어야 한다
    assert (pipe.run_dir / "context" / "exhibitions.csv").exists()
    for stage in ("plan", "plan-critic", "build", "build-critic"):
        prompt = next(p for s, p in calls if s == stage)
        assert "context/" in prompt, stage
    assert "context/exhibitions.csv" in next(p for s, p in calls if s == "build")


async def test_idea_slug_ending_in_mvp_is_not_renamed(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline_mod, "run_agent", make_fake_agent([]))
    run_dir = tmp_path / "20261012-153000-todo-mvp"
    run_dir.mkdir()
    pipe = Pipeline(RunConfig(idea="todo MVP", out_dir=tmp_path, budget_usd=5), run_dir)

    assert await pipe.run() is True
    assert pipe.run_dir == run_dir and run_dir.exists()
    assert json.loads((run_dir / "run_report.json").read_text())["renamed_from"] is None


async def test_budget_stops_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline_mod, "run_agent", make_fake_agent([]))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config = RunConfig(idea="x", out_dir=tmp_path, budget_usd=0.15)
    assert await Pipeline(config, run_dir).run() is False
    report = json.loads((run_dir / "run_report.json").read_text())
    assert "예산" in report["error"]


async def test_api_error_aborts_with_real_message(tmp_path, monkeypatch):
    calls = []

    async def failing_agent(*, stage, **kw):
        calls.append(stage)
        return AgentRun(stage, False, "success", 0.0, 1, 0.01, api_error=True, result_text="Credit balance is too low")

    monkeypatch.setattr(pipeline_mod, "run_agent", failing_agent)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    assert await Pipeline(RunConfig(idea="x", out_dir=tmp_path), run_dir).run() is False
    report = json.loads((run_dir / "run_report.json").read_text())
    assert "Credit balance is too low" in report["error"]
    assert calls == ["plan"]


async def test_design_auto_pauses_for_choice_then_resumes(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline_mod, "run_agent", make_fake_agent(calls))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config = RunConfig(idea="할 일 목록", out_dir=tmp_path, budget_usd=5, design="auto",
                       design_library=make_library(tmp_path / "lib"), design_candidates=3, design_seed=7)

    # 1차: 방향 3개를 만들고 사람의 선택을 기다리며 멈춘다. 실패가 아니다
    pipe = Pipeline(config, run_dir)
    assert await pipe.run() is False
    assert pipe.awaiting_choice
    assert [c[0] for c in calls] == ["plan", "plan-critic", "plan", "plan-critic", "design-directions"]
    report = json.loads((run_dir / "run_report.json").read_text())
    assert report["status"] == "awaiting_choice" and report["error"] is None
    assert report["design"]["seed"] == 7 and len(report["design"]["candidates"]) == 3
    assert all(c in calls[-1][1] for c in report["design"]["candidates"])
    readme = (run_dir / "README.md").read_text()
    assert "## C (unexpected)" in readme and "--resume run --choose <id>" in readme

    # 2차: 고른 방향으로 DESIGN.md를 쓰고 끝까지 간다. 방향은 다시 만들지 않는다
    calls.clear()
    config.choose, config.choose_reason = "C", "의외라서"
    pipe = Pipeline(config, run_dir)
    assert await pipe.run() is True
    stages = [c[0] for c in calls]
    assert stages == ["design", "design-critic", "build", "build-critic"]
    concepts = json.loads((run_dir / "concepts.json").read_text())
    assert concepts["chosen"] == "C" and concepts["chosen_by"] == "human" and concepts["reason"] == "의외라서"
    report = json.loads((run_dir / "run_report.json").read_text())
    assert report["status"] == "success"
    assert report["design"]["choice"] == {"id": "C", "kind": "unexpected", "reason": "의외라서"}
    assert report["stages"]["design"]["status"] == "passed"
    # 고른 방향의 원천이 Design 프롬프트에, DESIGN.md 안내가 Build와 Build critic 프롬프트에 들어가야 한다
    c_source = next(d for d in concepts["directions"] if d["id"] == "C")["sources"][0]
    assert f"design-candidates/{c_source}.md" in next(p for s, p in calls if s == "design")
    assert "DESIGN.md" in next(p for s, p in calls if s == "build")
    assert "DESIGN.md" in next(p for s, p in calls if s == "build-critic")
    assert "- design: passed" in (run_dir / "README.md").read_text()


async def test_design_unknown_choice_keeps_waiting(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline_mod, "run_agent", make_fake_agent([]))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config = RunConfig(idea="x", out_dir=tmp_path, budget_usd=5, design="auto",
                       design_library=make_library(tmp_path / "lib"), design_candidates=3)
    assert await Pipeline(config, run_dir).run() is False

    config.choose = "Z"
    pipe = Pipeline(config, run_dir)
    assert await pipe.run() is False
    report = json.loads((run_dir / "run_report.json").read_text())
    # 잘못 고른 것은 다시 고르면 된다. 대기 상태와 선택 안내가 그대로 남는다
    assert report["status"] == "awaiting_choice" and "'Z'는 방향 id가 아니다" in report["error"]
    assert pipe.awaiting_choice
    readme = (run_dir / "README.md").read_text()
    assert "직전 선택 오류" in readme and "## B (unexpected)" in readme


async def test_design_resume_keeps_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline_mod, "run_agent", make_fake_agent([]))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    lib = make_library(tmp_path / "lib", n=10)
    config = RunConfig(idea="x", out_dir=tmp_path, budget_usd=5, design="auto", design_library=lib, design_candidates=3,
                       choose="A")
    pipe = Pipeline(config, run_dir)
    pipe.state["design"] = {"seed": 1, "candidates": ["brand2", "brand5", "brand9"]}
    pipe._save()

    assert await pipe.run() is True
    assert sorted(p.stem for p in (run_dir / "design-candidates").glob("*.md")) == ["brand2", "brand5", "brand9"]


async def test_design_provided_file_skips_agent(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline_mod, "run_agent", make_fake_agent(calls))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    chosen = tmp_path / "mine.md"
    chosen.write_text("# 내가 고른 디자인")
    config = RunConfig(idea="x", out_dir=tmp_path, budget_usd=5, design=str(chosen))

    assert await Pipeline(config, run_dir).run() is True
    assert "design" not in [c[0] for c in calls]
    assert (run_dir / "DESIGN.md").read_text() == "# 내가 고른 디자인"
    report = json.loads((run_dir / "run_report.json").read_text())
    assert report["stages"]["design"]["status"] == "provided"
    assert "DESIGN.md" in next(p for s, p in calls if s == "build")


async def test_design_skipped_for_cli_app(tmp_path, monkeypatch):
    calls = []
    base = make_fake_agent(calls)

    async def cli_plan(**kw):
        run = await base(**kw)
        if kw["stage"] == "plan":
            spec = json.loads((kw["cwd"] / "spec.json").read_text())
            spec["smoke"] = {"command": "echo Fake Todo", "expect": "Fake Todo"}
            (kw["cwd"] / "spec.json").write_text(json.dumps(spec))
        return run

    monkeypatch.setattr(pipeline_mod, "run_agent", cli_plan)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config = RunConfig(idea="x", out_dir=tmp_path, budget_usd=5, design="auto", design_library=make_library(tmp_path / "lib"))

    await Pipeline(config, run_dir).run()
    assert "design" not in [c[0] for c in calls]
    state = json.loads((run_dir / "state.json").read_text())
    assert state["stages"]["design"]["status"] == "skipped"


async def test_stage_models_reach_each_session(tmp_path, monkeypatch):
    calls = []
    fake = make_fake_agent(calls)
    models = {}

    async def recording_agent(*, stage, model, **kw):
        models.setdefault(stage, set()).add(model)
        return await fake(stage=stage, **kw)

    monkeypatch.setattr(pipeline_mod, "run_agent", recording_agent)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config = RunConfig(idea="할 일 목록", out_dir=tmp_path, budget_usd=5, model="default-model",
                       stage_models={"plan": "plan-model", "critic": "critic-model", "build-critic": "bc-model"})

    assert await Pipeline(config, run_dir).run() is True
    assert models == {"plan": {"plan-model"}, "plan-critic": {"critic-model"},
                      "build": {"default-model"}, "build-critic": {"bc-model"}}
    report = json.loads((run_dir / "run_report.json").read_text())
    assert report["stage_models"] == config.stage_models
    assert [(r["stage"], r["model"]) for r in report["runs"]][:2] == [("plan", "plan-model"), ("plan-critic", "critic-model")]
