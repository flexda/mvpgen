"""SDK 호출을 가짜 에이전트로 바꿔 전체 흐름(Stop gate, critic 개정, 최종 검증)을 오프라인으로 확인한다."""

import json
import sys

import mvpgen.pipeline as pipeline_mod
from mvpgen.agents import AgentRun
from mvpgen.pipeline import Pipeline, RunConfig
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


def fake_spec():
    return {
        "name": "fake-todo", "summary": "할 일 목록", "stack": "Python stdlib",
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
