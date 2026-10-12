import asyncio
import os

from mvpgen.envfiles import app_env, load_claude_env, load_mvp_env, parse_env_file
from mvpgen.guards import make_guard


def test_parse_env_file(tmp_path):
    p = tmp_path / "x.env"
    p.write_text(
        "# comment\n\nA=1\nexport B = two \nC=\"quoted # value\"\nD='single'\nE=\nF=plain # trailing\nbad line\n"
    )
    assert parse_env_file(p) == {"A": "1", "B": "two", "C": "quoted # value", "D": "single", "F": "plain"}
    assert parse_env_file(tmp_path / "missing.env") == {}


def test_load_claude_env_does_not_override_shell(tmp_path, monkeypatch):
    (tmp_path / "claude.env").write_text("ANTHROPIC_API_KEY=from-file\nOTHER_X=1\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-shell")
    monkeypatch.delenv("OTHER_X", raising=False)
    assert load_claude_env(tmp_path) == ["OTHER_X"]
    assert os.environ["ANTHROPIC_API_KEY"] == "from-shell"


def test_app_env_strips_claude_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-claude")
    (tmp_path / "mvp.env").write_text("WEATHER_KEY=w-123\n")
    env = app_env(load_mvp_env(tmp_path))
    assert "ANTHROPIC_API_KEY" not in env and env["WEATHER_KEY"] == "w-123"


def _call(guard, tool, tool_input):
    return asyncio.run(guard({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}, None, None))


def test_guard_blocks_secret_folder_and_values(tmp_path):
    root = tmp_path / "run"
    secrets = tmp_path / "secrets"
    root.mkdir(); secrets.mkdir()
    guard = make_guard(root, [root / "app"], [secrets], ["w-1234567890"])

    assert _call(guard, "Read", {"file_path": str(secrets / "mvp.env")})
    assert _call(guard, "Grep", {"pattern": "KEY", "path": str(secrets)})
    assert _call(guard, "Bash", {"command": f"cat {secrets}/mvp.env"})
    assert _call(guard, "Bash", {"command": "cat ../secrets/mvp.env"})
    assert _call(guard, "Write", {"file_path": str(root / "app" / "c.py"), "content": "KEY='w-1234567890'"})
    assert _call(guard, "Bash", {"command": "curl -H 'k: w-1234567890' x"})

    assert _call(guard, "Write", {"file_path": str(root / "app" / "c.py"), "content": "os.environ['WEATHER_KEY']"}) == {}
    assert _call(guard, "Read", {"file_path": str(root / "spec.json")}) == {}
    assert _call(guard, "Bash", {"command": "echo $WEATHER_KEY | wc -c"}) == {}
