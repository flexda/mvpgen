"""SDK 호출을 가짜 에이전트로 바꿔 전체 흐름(Stop gate, critic 개정, 최종 검증)을 오프라인으로 확인한다."""

import json
import sys
from pathlib import Path

import mvpgen.pipeline as pipeline_mod
from mvpgen.agents import AgentRun
from mvpgen.pipeline import Pipeline, RunConfig
from mvpgen.design import DESIGN_HEADINGS
from mvpgen.research import RESEARCH_HEADINGS
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


DESIGN_MD = '---\ncolors:\n  text: "#111111"\n  background: "#ffffff"\n---\n\n' + "\n\n".join(f"{h}\n" + "내용 " * 120 for h in DESIGN_HEADINGS)


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


ISSUE = {"severity": "major", "location": "spec-candidates/b.json", "problem": "범위가 넓다", "fix": "기능을 줄여라"}
# 기본 거르기: a는 제외, b만 viable이라 사람이 고를 구현 후보가 없다
SCREEN = {"a": {"viable": False, "score": 40}, "b": {"viable": True, "score": 90}}


def make_fake_agent(calls, fail_first=("prd-critic",), screen=None):
    """fail_first에 든 critic은 1라운드에 불합격을 준다. screen은 후보별 거르기 판정이다."""
    screen = screen or SCREEN
    async def fake_run_agent(*, stage, cwd, gate=None, prompt="", **kw):
        calls.append((stage, prompt))
        rnd = int(str(kw["log_path"]).rsplit("-r", 1)[1].split(".")[0])
        if stage == "prd":
            (cwd / "PRD.md").write_text("\n\n".join(f"{h}\n" + "내용 " * 40 for h in PRD_HEADINGS))
        elif stage == "spec" and not (cwd / "spec.json").exists():
            # 첫 종료 시도: 후보가 없어 gate가 막아야 한다
            first = await gate({"hook_event_name": "Stop", "stop_hook_active": False}, None, None)
            assert first["decision"] == "block" and "spec-candidates" in first["reason"]
            (cwd / "spec-candidates").mkdir(exist_ok=True)
            for cid, approach in (("a", "MMCA API 실시간"), ("b", "수집 CSV")):
                cand = {"decision": "데이터 출처", "approach": approach, "spec": {**fake_spec(), "summary": f"후보 {cid}"}}
                (cwd / "spec-candidates" / f"{cid}.json").write_text(json.dumps(cand))
            assert await gate({"hook_event_name": "Stop", "stop_hook_active": True}, None, None) == {}
        elif stage.startswith("research-"):
            cid = stage.removeprefix("research-")
            first = await gate({"hook_event_name": "Stop", "stop_hook_active": False}, None, None)
            assert first["decision"] == "block" and f"research/{cid}.md" in first["reason"]
            (cwd / "research" / f"{cid}.md").write_text("\n\n".join(f"{h}\n" + "조사 " * 60 for h in RESEARCH_HEADINGS))
            assert await gate({"hook_event_name": "Stop", "stop_hook_active": True}, None, None) == {}
        elif stage == "spec":
            spec = json.loads((cwd / "spec.json").read_text())
            (cwd / "spec.json").write_text(json.dumps({**spec, "summary": spec["summary"] + " (고침)"}))
        elif stage == "design-directions":
            # 첫 종료 시도: 산출물이 없어 gate가 막아야 한다
            first = await gate({"hook_event_name": "Stop", "stop_hook_active": False}, None, None)
            assert first["decision"] == "block" and "concepts.json" in first["reason"]
            cands = sorted(p.stem for p in (cwd / "design-candidates").glob("*.md") if p.name != "INDEX.md")
            dirs = [{"id": i, "kind": k, "sources": [cands[n]], "metaphor": "m", "first_screen": "f", "risks": "r",
                     "colors": {"text": "#111111", "background": "#fafafa"}}
                    for n, (i, k) in enumerate([("A", "baseline"), ("B", "unexpected"), ("C", "unexpected")])]
            (cwd / "concepts.json").write_text(json.dumps({"directions": dirs}))
            # 방향만 있고 미리보기가 없으면 아직 막혀야 한다
            second = await gate({"hook_event_name": "Stop", "stop_hook_active": True}, None, None)
            assert second["decision"] == "block" and "previews/A.html" in second["reason"]
            (cwd / "previews").mkdir(exist_ok=True)
            for i in "ABC":
                (cwd / "previews" / f"{i}.html").write_text(f'<main><section data-feature="F1">할 일 {i}</section></main>')
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
            if stage == "spec-screen-critic":
                verdicts = [{"id": cid, "summary": f"후보 {cid}", **v} for cid, v in screen.items()]
                viable = [cid for cid, v in screen.items() if v["viable"]]
                path.write_text(json.dumps({"summary": "비교", "candidates": verdicts, "recommended": viable[-1] if viable else "a"}))
                assert gate.checker()[0]
                return AgentRun(stage, True, "success", 0.1, 3, 0.01, gate=gate.stats())
            passed = not (stage in fail_first and rnd == 1)
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
    assert stages == ["prd", "prd-critic", "prd", "prd-critic", "spec", "research-a", "research-b", "spec-screen-critic", "build", "build-critic"]
    # 두 번째 prd 호출에는 critic 지적이 전달되어야 한다
    assert "범위가 넓다" in calls[2][1]
    # spec critic은 두 후보를 거르기만 했고, viable 후보가 b 하나라 b가 spec.json이 되었다
    critic_prompt = calls[7][1]
    assert "spec-candidates/a.json" in critic_prompt and "spec-candidates/b.json" in critic_prompt
    # 조사 결과가 후보 옆에 근거로 붙는다
    assert "research/a.md" in critic_prompt and "research/b.md" in critic_prompt
    assert json.loads((run_dir / "spec.json").read_text())["summary"] == "후보 b"

    report = json.loads((run_dir / "run_report.json").read_text())
    assert report["success"] is True
    assert [r["score"] for r in report["stages"]["prd"]["rounds"]] == [60, 90]
    assert report["choice"]["spec"] == {"id": "b", "by": "only_viable", "reason": None}
    assert sorted(report["stages"]["screen"]["order"]) == ["a", "b"]
    # 거르기에서 지적 없이 통과한 후보라 spec critic을 다시 부르지 않았다
    assert report["stages"]["spec"] == {"status": "passed", "rounds": [], "from_screening": True}
    assert report["stages"]["build"]["status"] == "passed"
    assert report["stages"]["verify"]["status"] == "passed"
    build_run = next(r for r in report["runs"] if r["stage"] == "build")
    assert build_run["gate"]["blocks"] == 1
    assert abs(report["cost_usd"] - 1.0) < 1e-9
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

    # 저장소의 예전 [plan] 교훈이 PRD와 Spec 시스템 프롬프트에 들어가고, 새 지적도 같은 파일에 쌓여야 한다
    assert "이전 실행의 기획 지적" in next(s for st, s in systems if st == "prd")
    assert "이전 실행의 기획 지적" in next(s for st, s in systems if st == "spec")
    assert "- [prd] 범위가 넓다" in lessons.read_text()
    assert "범위가 넓다" in lessons.read_text()
    assert not (out / "lessons.md").exists()


async def test_fallback_folder_renamed_after_spec(tmp_path, monkeypatch):
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
    assert (new_dir / "snapshots" / "prd").is_dir() and (new_dir / "snapshots" / "build").is_dir()
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
    for stage in ("prd", "prd-critic", "spec", "spec-screen-critic", "build-critic"):
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
    for stage in ("prd", "prd-critic", "spec", "spec-screen-critic", "build", "build-critic"):
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
    assert calls == ["prd"]


async def test_design_auto_pauses_for_choice_then_resumes(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline_mod, "run_agent", make_fake_agent(calls))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config = RunConfig(idea="할 일 목록", out_dir=tmp_path, budget_usd=5, design="auto",
                       design_library=make_library(tmp_path / "lib"))

    # 1차: 방향 3개를 만들고 사람의 선택을 기다리며 멈춘다. 실패가 아니다
    pipe = Pipeline(config, run_dir)
    assert await pipe.run() is False
    assert pipe.awaiting_choice
    assert [c[0] for c in calls] == ["prd", "prd-critic", "prd", "prd-critic", "spec", "research-a", "research-b", "spec-screen-critic", "design-directions"]
    report = json.loads((run_dir / "run_report.json").read_text())
    assert report["status"] == "awaiting_choice" and report["error"] is None
    # 무작위로 뽑지 않고 라이브러리 전체를 목록과 함께 두며, 에이전트가 목록을 보고 고른다
    assert len(report["design"]["candidates"]) == 5 and "seed" not in report["design"]
    assert "design-candidates/INDEX.md" in calls[-1][1]
    assert "- brand3: " in (run_dir / "design-candidates" / "INDEX.md").read_text()
    readme = (run_dir / "README.md").read_text()
    # viable 구현 후보가 b 하나라 디자인 방향만 고르면 된다
    assert "### C (unexpected)" in readme and "--resume run" in readme and "--choose-design <id>" in readme
    assert "- 미리보기: previews/C.html" in readme
    # 미리보기는 기능 id를 받아 만든다
    assert "data-feature로 표시할 기능: F1" in calls[-1][1]
    assert "--choose-spec" not in readme and "고르는 방식: b로 정해짐 (only_viable)" in readme

    # 2차: 고른 방향으로 DESIGN.md를 쓰고 끝까지 간다. 방향은 다시 만들지 않는다
    calls.clear()
    config.choose_design, config.design_reason = "C", "의외라서"
    pipe = Pipeline(config, run_dir)
    assert await pipe.run() is True
    stages = [c[0] for c in calls]
    # 사람이 미리보기로 골랐으므로 DESIGN.md는 critic 없이 코드 검사만 거친다
    assert stages == ["design", "build", "build-critic"]
    concepts = json.loads((run_dir / "concepts.json").read_text())
    assert concepts["chosen"] == "C" and concepts["chosen_by"] == "human" and concepts["reason"] == "의외라서"
    report = json.loads((run_dir / "run_report.json").read_text())
    assert report["status"] == "success"
    assert report["choice"]["design"] == {"id": "C", "kind": "unexpected", "reason": "의외라서"}
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
                       design_library=make_library(tmp_path / "lib"))
    assert await Pipeline(config, run_dir).run() is False

    config.choose_design = "Z"
    pipe = Pipeline(config, run_dir)
    assert await pipe.run() is False
    report = json.loads((run_dir / "run_report.json").read_text())
    # 잘못 고른 것은 다시 고르면 된다. 대기 상태와 선택 안내가 그대로 남는다
    assert report["status"] == "awaiting_choice" and "'Z'는 방향 id가 아니다" in report["error"]
    assert pipe.awaiting_choice
    readme = (run_dir / "README.md").read_text()
    assert "직전 선택 오류" in readme and "### B (unexpected)" in readme


async def test_design_resume_keeps_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline_mod, "run_agent", make_fake_agent([]))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    lib = make_library(tmp_path / "lib", n=10)
    config = RunConfig(idea="x", out_dir=tmp_path, budget_usd=5, design="auto", design_library=lib,
                       choose_design="A")
    pipe = Pipeline(config, run_dir)
    pipe.state["design"] = {"library": str(lib), "candidates": ["brand2", "brand5", "brand9"]}
    pipe._save()

    assert await pipe.run() is True
    # 이어 할 때는 처음 기록한 원천 목록을 그대로 쓴다
    assert sorted(p.stem for p in (run_dir / "design-candidates").glob("*.md")) == ["INDEX", "brand2", "brand5", "brand9"]


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
    # 지정한 파일은 critic을 거치지 않으니, 확인할 수 있는 것을 경고로 남긴다
    assert any("프런트매터" in w for w in report["stages"]["design"]["warnings"])
    assert "DESIGN.md" in next(p for s, p in calls if s == "build")


async def test_design_skipped_for_cli_app(tmp_path, monkeypatch):
    calls = []
    base = make_fake_agent(calls)

    async def cli_plan(**kw):
        run = await base(**kw)
        if kw["stage"] == "spec":
            for path in (kw["cwd"] / "spec-candidates").glob("*.json"):
                cand = json.loads(path.read_text())
                cand["spec"]["smoke"] = {"command": "echo Fake Todo", "expect": "Fake Todo"}
                path.write_text(json.dumps(cand))
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
    # plan은 prd와 spec 양쪽에 쓰인다
    assert models == {"prd": {"plan-model"}, "prd-critic": {"critic-model"}, "spec": {"plan-model"},
                      "research-a": {"plan-model"}, "research-b": {"plan-model"},
                      "spec-screen-critic": {"critic-model"}, "build": {"default-model"}, "build-critic": {"bc-model"}}
    report = json.loads((run_dir / "run_report.json").read_text())
    assert report["stage_models"] == config.stage_models
    assert [(r["stage"], r["model"]) for r in report["runs"]][:2] == [("prd", "plan-model"), ("prd-critic", "critic-model")]


async def test_chosen_spec_with_screening_issues_is_refined(tmp_path, monkeypatch):
    calls = []
    screen = {"a": {"viable": False, "score": 40}, "b": {"viable": True, "score": 70, "issues": [ISSUE]}}
    fake = make_fake_agent(calls, fail_first=(), screen=screen)
    writables = {}

    async def recording(**kw):
        writables.setdefault(kw["stage"], []).append([p.name for p in kw["writable"]])
        return await fake(**kw)

    monkeypatch.setattr(pipeline_mod, "run_agent", recording)
    run_dir = tmp_path / "run"
    (run_dir / "context").mkdir(parents=True)
    (run_dir / "context" / "data.csv").write_text("title\nA\n")
    (run_dir / "brief.md").write_text("# 할 일 목록")
    assert await Pipeline(RunConfig(idea="할 일 목록", out_dir=tmp_path, budget_usd=5), run_dir).run() is True

    assert [c[0] for c in calls][:8] == ["prd", "prd-critic", "spec", "research-a", "research-b", "spec-screen-critic",
                                         "spec", "spec-critic"]
    # 개정 세션은 거르기에서 이 후보에 남은 지적과 함께, 고른 후보, 참고 자료, brief를 안다
    for needle in ("범위가 넓다", "spec-candidates/b.json", "context/data.csv", "brief.md"):
        assert needle in calls[6][1], needle
    # 후보를 만들 때는 후보 폴더를, 고친 뒤에는 고른 spec.json만 쓸 수 있다
    assert writables["spec"] == [["spec-candidates"], ["spec.json"]]
    assert "spec-candidates/a.json" not in calls[7][1]
    assert json.loads((run_dir / "spec.json").read_text())["summary"] == "후보 b (고침)"


async def test_two_viable_specs_pause_for_a_human_choice(tmp_path, monkeypatch):
    calls = []
    screen = {"a": {"viable": True, "score": 85}, "b": {"viable": True, "score": 90}}
    monkeypatch.setattr(pipeline_mod, "run_agent", make_fake_agent(calls, fail_first=(), screen=screen))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config = RunConfig(idea="할 일 목록", out_dir=tmp_path, budget_usd=5)

    pipe = Pipeline(config, run_dir)
    assert await pipe.run() is False and pipe.awaiting_choice
    assert [c[0] for c in calls][-1] == "spec-screen-critic"
    readme = (run_dir / "README.md").read_text()
    # 구현 후보마다 결정, 선택, 점수, 조사로 본 위험을 보여 주고, 디자인 방향은 묻지 않는다(design off)
    assert "### a (viable, 85점)" in readme and "### b (추천, viable, 90점)" in readme
    assert "- 이 후보의 방식: MMCA API 실시간" in readme and "조사로 본 위험" in readme
    assert "--choose-spec <id>" in readme and "--choose-design" not in readme

    # 고르지 않은 것을 고르면 대기가 남는다
    calls.clear()
    config.choose_spec = "z"
    pipe = Pipeline(config, run_dir)
    assert await pipe.run() is False and pipe.awaiting_choice and calls == []

    config.choose_spec, config.spec_reason = "a", "실시간이 낫다"
    pipe = Pipeline(config, run_dir)
    assert await pipe.run() is True
    assert json.loads((run_dir / "spec.json").read_text())["summary"] == "후보 a"
    report = json.loads((run_dir / "run_report.json").read_text())
    assert report["choice"]["spec"] == {"id": "a", "by": "human", "reason": "실시간이 낫다"}


async def test_recommended_choice_runs_without_pausing(tmp_path, monkeypatch):
    calls = []
    screen = {"a": {"viable": True, "score": 85}, "b": {"viable": True, "score": 90}}
    monkeypatch.setattr(pipeline_mod, "run_agent", make_fake_agent(calls, fail_first=(), screen=screen))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config = RunConfig(idea="할 일 목록", out_dir=tmp_path, budget_usd=5, choose_spec="recommended")
    assert await Pipeline(config, run_dir).run() is True
    report = json.loads((run_dir / "run_report.json").read_text())
    assert report["choice"]["spec"]["id"] == "b" and report["choice"]["spec"]["by"] == "recommended"


async def test_no_viable_spec_regenerates_then_fails(tmp_path, monkeypatch):
    calls = []
    screen = {"a": {"viable": False, "score": 30, "issues": [ISSUE]}, "b": {"viable": False, "score": 20}}
    monkeypatch.setattr(pipeline_mod, "run_agent", make_fake_agent(calls, fail_first=(), screen=screen))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config = RunConfig(idea="할 일 목록", out_dir=tmp_path, budget_usd=5, max_review_rounds=1)
    assert await Pipeline(config, run_dir).run() is False
    stages = [c[0] for c in calls]
    # 지적을 반영해 후보와 조사를 처음부터 다시 만든다
    assert stages.count("spec") == 2 and stages.count("research-a") == 2 and stages.count("spec-screen-critic") == 2
    second_spec = [p for s, p in calls if s == "spec"][1]
    assert "모두 실행할 수 없다고" in second_spec and "범위가 넓다" in second_spec
    report = json.loads((run_dir / "run_report.json").read_text())
    assert "viable" in report["error"] and report["stages"]["screen"]["status"] == "failed"
    # 거르기의 major 지적도 교훈으로 쌓인다
    assert "- [spec] 범위가 넓다" in (tmp_path / "lessons.md").read_text()


async def test_resume_repairs_broken_spec_json(tmp_path, monkeypatch):
    """개정이 중간에 끊겨 spec.json이 깨진 채 멈춘 실행을 이어 가면, 검사 결과를 지적으로 삼아 고친다."""
    calls = []
    fake = make_fake_agent(calls, fail_first=())

    async def repairing(**kw):
        if kw["stage"] == "spec" and (kw["cwd"] / "spec.json").exists():
            calls.append((kw["stage"], kw["prompt"]))
            (kw["cwd"] / "spec.json").write_text(json.dumps(fake_spec()))
            return AgentRun("spec", True, "success", 0.1, 3, 0.01)
        return await fake(**kw)

    monkeypatch.setattr(pipeline_mod, "run_agent", repairing)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "PRD.md").write_text("\n\n".join(f"{h}\n" + "내용 " * 40 for h in PRD_HEADINGS))
    broken = fake_spec()
    del broken["intent"]
    (run_dir / "spec.json").write_text(json.dumps(broken))
    (run_dir / "spec-candidates").mkdir()
    (run_dir / "spec-candidates" / "b.json").write_text(json.dumps({"decision": "d", "approach": "x", "spec": fake_spec()}))
    (run_dir / "reviews").mkdir()
    (run_dir / "reviews" / "spec-screen-r1.json").write_text(json.dumps({
        "summary": "s", "recommended": "b", "candidates": [{"id": "b", "viable": True, "score": 90, "summary": "좋다"}]}))
    (run_dir / "state.json").write_text(json.dumps({
        "idea": "할 일 목록", "runs": [], "cost_usd": 0.0,
        "stages": {"prd": {"status": "passed", "rounds": []}, "spec": {"status": "failed", "rounds": []},
                   "screen": {"status": "passed", "rounds": [], "review": "reviews/spec-screen-r1.json"},
                   "choice": {"status": "done", "rounds": []}},
        "choice": {"spec": {"id": "b", "by": "human", "reason": None}},
    }))

    assert await Pipeline(RunConfig(idea="할 일 목록", out_dir=tmp_path, budget_usd=5), run_dir).run() is True
    assert calls[0][0] == "spec" and "intent가 없다" in calls[0][1]
    assert json.loads((run_dir / "spec.json").read_text())["intent"]


async def test_resume_reuses_candidates_and_finished_research(tmp_path, monkeypatch):
    """조사 중에 멈춘 실행을 이어 가면 후보는 다시 만들지 않고, 끝난 조사도 건너뛴다."""
    calls = []
    monkeypatch.setattr(pipeline_mod, "run_agent", make_fake_agent(calls, fail_first=()))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "PRD.md").write_text("\n\n".join(f"{h}\n" + "내용 " * 40 for h in PRD_HEADINGS))
    (run_dir / "spec-candidates").mkdir()
    for cid, approach in (("a", "API"), ("b", "CSV")):
        cand = {"decision": "데이터 출처", "approach": approach, "spec": {**fake_spec(), "summary": f"후보 {cid}"}}
        (run_dir / "spec-candidates" / f"{cid}.json").write_text(json.dumps(cand))
    (run_dir / "research").mkdir()
    (run_dir / "research" / "a.md").write_text("\n\n".join(f"{h}\n" + "조사 " * 60 for h in RESEARCH_HEADINGS))
    (run_dir / "state.json").write_text(json.dumps({
        "idea": "할 일 목록", "stages": {"prd": {"status": "passed", "rounds": []}}, "runs": [], "cost_usd": 0.0}))

    assert await Pipeline(RunConfig(idea="할 일 목록", out_dir=tmp_path, budget_usd=5), run_dir).run() is True
    assert [c[0] for c in calls][:2] == ["research-b", "spec-screen-critic"]


async def test_no_research_skips_web_sessions(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline_mod, "run_agent", make_fake_agent(calls, fail_first=()))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config = RunConfig(idea="할 일 목록", out_dir=tmp_path, budget_usd=5, research=False)
    assert await Pipeline(config, run_dir).run() is True
    assert not any(s.startswith("research-") for s, _ in calls)
    assert "research/" not in next(p for s, p in calls if s == "spec-screen-critic")


async def test_research_sessions_get_web_tools_and_one_writable_file(tmp_path, monkeypatch):
    fake = make_fake_agent([], fail_first=())
    seen = {}

    async def recording(**kw):
        if kw["stage"].startswith("research-"):
            seen[kw["stage"]] = (kw["tools"], [p.relative_to(kw["cwd"]) for p in kw["writable"]])
        return await fake(**kw)

    monkeypatch.setattr(pipeline_mod, "run_agent", recording)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    assert await Pipeline(RunConfig(idea="할 일 목록", out_dir=tmp_path, budget_usd=5), run_dir).run() is True
    tools, writable = seen["research-a"]
    assert {"WebSearch", "WebFetch"} <= set(tools) and "Bash" not in tools
    assert [str(w) for w in writable] == ["research/a.md"]


async def test_critic_only_points_at_existing_research(tmp_path, monkeypatch):
    """조사 도중 멈춘 실행을 --no-research로 이어 가면, 조사가 끝난 후보에만 조사 파일을 붙인다."""
    calls = []
    monkeypatch.setattr(pipeline_mod, "run_agent", make_fake_agent(calls, fail_first=()))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "PRD.md").write_text("\n\n".join(f"{h}\n" + "내용 " * 40 for h in PRD_HEADINGS))
    (run_dir / "spec-candidates").mkdir()
    for cid, approach in (("a", "API"), ("b", "CSV")):
        cand = {"decision": "데이터 출처", "approach": approach, "spec": fake_spec()}
        (run_dir / "spec-candidates" / f"{cid}.json").write_text(json.dumps(cand))
    (run_dir / "research").mkdir()
    (run_dir / "research" / "a.md").write_text("\n\n".join(f"{h}\n" + "조사 " * 60 for h in RESEARCH_HEADINGS))
    (run_dir / "state.json").write_text(json.dumps({
        "idea": "할 일 목록", "stages": {"prd": {"status": "passed", "rounds": []}}, "runs": [], "cost_usd": 0.0}))

    config = RunConfig(idea="할 일 목록", out_dir=tmp_path, budget_usd=5, research=False)
    assert await Pipeline(config, run_dir).run() is True
    critic_prompt = next(p for s, p in calls if s == "spec-screen-critic")
    assert "research/a.md" in critic_prompt and "research/b.md" not in critic_prompt


SOURCES_TOML = Path(__file__).resolve().parent.parent / "design-sources.toml"
VOLT = "https://github.com/VoltAgent/awesome-design-md/blob/main/design-md/{}/DESIGN.md"


def with_refs(base, seen):
    """design-refs 세션을 흉내 낸다. 받은 웹 범위를 seen에 남긴다."""
    async def agent(**kw):
        if kw["stage"] != "design-refs":
            return await base(**kw)
        seen["web_domains"] = kw.get("web_domains")
        seen["tools"] = kw["tools"]
        picks = [{"url": VOLT.format(n), "why": f"{n}가 어울린다"} for n in ("wired", "vogue", "nike")]
        (kw["cwd"] / "design-refs.json").write_text(json.dumps({"type": "web", "picks": picks}))
        assert kw["gate"].checker()[0]
        return AgentRun("design-refs", True, "success", 0.1, 3, 0.01)
    return agent


async def test_design_sources_come_from_reference_sites(tmp_path, monkeypatch):
    calls, seen = [], {}
    monkeypatch.setattr(pipeline_mod, "run_agent", with_refs(make_fake_agent(calls), seen))
    monkeypatch.setattr(pipeline_mod, "fetch", lambda url: f'---\ndescription: "{url.split("/")[-2]} style"\n---\n# x')
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config = RunConfig(idea="할 일 목록", out_dir=tmp_path, budget_usd=5, design="auto",
                       design_library=make_library(tmp_path / "lib"), design_sources=SOURCES_TOML)

    assert await Pipeline(config, run_dir).run() is False
    # 웹 도구는 레퍼런스 도메인으로 묶이고, 셸은 없다
    assert seen["web_domains"] == ["github.com", "raw.githubusercontent.com"] and "Bash" not in seen["tools"]
    state = json.loads((run_dir / "state.json").read_text())
    design = state["design"]
    assert design["source"] == "references" and design["type"] == "web"
    assert design["candidates"] == ["voltagent-wired", "voltagent-vogue", "voltagent-nike"]
    assert design["refs"]["voltagent-wired"]["license"] == "MIT"
    index = (run_dir / "design-candidates" / "INDEX.md").read_text()
    assert "- voltagent-wired: wired style (출처: https://github.com/VoltAgent" in index
    # 멈춤 README에 방향마다 출처가 붙는다
    assert "- 출처: https://github.com/VoltAgent/awesome-design-md/blob/main/design-md/" in (run_dir / "README.md").read_text()

    config.choose_design = "B"
    assert await Pipeline(config, run_dir).run() is True
    design_md = (run_dir / "DESIGN.md").read_text()
    b_source = next(d for d in json.loads((run_dir / "concepts.json").read_text())["directions"] if d["id"] == "B")["sources"][0]
    assert "## Sources" in design_md and design["refs"][b_source]["url"] in design_md


async def test_failed_reference_downloads_fall_back_to_library(tmp_path, monkeypatch):
    calls, seen = [], {}
    monkeypatch.setattr(pipeline_mod, "run_agent", with_refs(make_fake_agent(calls), seen))

    def broken(url):
        raise OSError("network down")

    monkeypatch.setattr(pipeline_mod, "fetch", broken)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config = RunConfig(idea="할 일 목록", out_dir=tmp_path, budget_usd=5, design="auto",
                       design_library=make_library(tmp_path / "lib"), design_sources=SOURCES_TOML)
    assert await Pipeline(config, run_dir).run() is False
    design = json.loads((run_dir / "state.json").read_text())["design"]
    assert design["source"] == "library" and "0개" in design["fallback_reason"]
    assert calls[-1][0] == "design-directions"
