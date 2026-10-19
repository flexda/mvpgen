import json

from typer.testing import CliRunner

import mvpgen.identity as identity_mod
import mvpgen.pipeline as pipeline_mod
from mvpgen.cli import EXIT_AWAITING_CHOICE, app


def paused_run(out, **state_over):
    run_dir = out / "run"
    run_dir.mkdir(parents=True)
    state = {
        "idea": "x", "model": "m0", "stage_models": {"build": "b"},
        "settings": {"model": "m0", "stage_models": {"build": "b"}, "effort": "low", "budget_usd": 3.0, "design": "auto",
                     "spec_candidates": 3},
        "stages": {"design": {"status": "awaiting_choice", "rounds": []}}, "runs": [], "cost_usd": 0.0,
    }
    state.update(state_over)
    (run_dir / "state.json").write_text(json.dumps(state))
    return run_dir


def invoke(tmp_path, monkeypatch, *args, awaiting=True):
    seen = {}

    class FakePipeline:
        def __init__(self, config, run_dir):
            seen["config"] = config
            self.awaiting_choice = awaiting

        async def run(self):
            return False

    monkeypatch.setattr(identity_mod, "detect_auth", lambda: ("subscription", []))
    monkeypatch.setattr(pipeline_mod, "Pipeline", FakePipeline)
    (tmp_path / "secrets").mkdir(exist_ok=True)
    (tmp_path / "lib").mkdir(exist_ok=True)
    result = CliRunner().invoke(app, [
        "--out", str(tmp_path / "out"), "--secrets", str(tmp_path / "secrets"), "--design-library", str(tmp_path / "lib"),
        "--no-gha-oidc", *args,
    ])
    return result, seen.get("config")


def test_resume_with_choice_keeps_first_run_settings_and_exits_awaiting(tmp_path, monkeypatch):
    paused_run(tmp_path / "out")
    result, config = invoke(tmp_path, monkeypatch, "--resume", "run", "--choose", "C", "--reason", "의외라서")
    assert result.exit_code == EXIT_AWAITING_CHOICE, result.output
    assert (config.model, config.stage_models, config.effort, config.budget_usd) == ("m0", {"build": "b"}, "low", 3.0)
    assert config.spec_candidates == 3
    assert (config.choose, config.choose_reason) == ("C", "의외라서")


def test_resume_flags_override_saved_settings(tmp_path, monkeypatch):
    paused_run(tmp_path / "out")
    _, config = invoke(tmp_path, monkeypatch, "--resume", "run", "--choose", "C", "--stage-model", "critic=c", "--budget", "8")
    assert config.stage_models == {"build": "b", "critic": "c"} and config.budget_usd == 8.0 and config.model == "m0"


def test_choose_rejected_when_run_is_not_waiting(tmp_path, monkeypatch):
    paused_run(tmp_path / "out", stages={"design": {"status": "passed", "rounds": []}})
    result, config = invoke(tmp_path, monkeypatch, "--resume", "run", "--choose", "C")
    assert result.exit_code == 2 and config is None


def test_choose_needs_resume(tmp_path, monkeypatch):
    result, config = invoke(tmp_path, monkeypatch, "idea", "--choose", "C")
    assert result.exit_code == 2 and config is None


def test_new_run_uses_defaults_and_failure_exits_1(tmp_path, monkeypatch):
    result, config = invoke(tmp_path, monkeypatch, "todo app", awaiting=False)
    assert result.exit_code == 1
    assert (config.model, config.effort, config.budget_usd, config.design) == ("claude-opus-5-5", "high", 10.0, "auto")


def test_brief_alone_names_the_run_and_is_copied(tmp_path, monkeypatch):
    brief = tmp_path / "brief.md"
    brief.write_text("# todo list\n- 대상: 혼자 쓰는 사람")
    result, config = invoke(tmp_path, monkeypatch, "--brief", str(brief), awaiting=False)
    assert result.exit_code == 1, result.output
    assert config.idea == "todo list"
    [run_dir] = (tmp_path / "out").iterdir()
    assert run_dir.name.endswith("-todo-list") and (run_dir / "brief.md").read_text() == brief.read_text()


def test_brief_refused_on_resume(tmp_path, monkeypatch):
    paused_run(tmp_path / "out")
    brief = tmp_path / "brief.md"
    brief.write_text("# x")
    result, config = invoke(tmp_path, monkeypatch, "--resume", "run", "--brief", str(brief))
    assert result.exit_code == 2 and config is None
