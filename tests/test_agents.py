import asyncio

from mvpgen import agents


def test_session_disables_auto_memory_and_keeps_env(tmp_path, monkeypatch):
    seen = {}

    async def fake_query(*, prompt, options):
        seen["env"] = options.env
        return
        yield

    monkeypatch.setattr(agents, "query", fake_query)
    asyncio.run(agents.run_agent(
        stage="prd", system_prompt="s", prompt="p", cwd=tmp_path, tools=["Read"], writable=[], model="m",
        effort="high", max_turns=1, max_budget_usd=1.0, log_path=tmp_path / "log.txt", env={"MMCA_SERVICE_KEY": "k"},
    ))
    assert seen["env"] == {"MMCA_SERVICE_KEY": "k", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}
