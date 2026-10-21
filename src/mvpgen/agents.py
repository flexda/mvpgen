"""claude_agent_sdk.query()를 단계 실행 단위로 감싼다."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKError,
    HookMatcher,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from mvpgen.gates import StopGate
from mvpgen.guards import make_guard

GATE_HOOK_TIMEOUT_S = 1800
# 실행 폴더가 저장소 안(workspace/)에 있으면 세션이 저장소의 Claude Code 자동 메모리를 읽는다.
# setting_sources=[]로는 꺼지지 않아서 환경변수로 끈다 (code.claude.com/docs/en/memory)
SESSION_ENV = {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}
# critic이 화면 캡처(PNG)를 Read로 열면 base64로 한 메시지에 실려 SDK 기본 버퍼(1MB)를 넘는다
SESSION_BUFFER_BYTES = 16 * 1024 * 1024


@dataclass
class AgentRun:
    stage: str
    ok: bool
    subtype: str
    cost_usd: float
    turns: int
    duration_s: float
    session_id: str | None = None
    error: str | None = None
    gate: dict[str, Any] | None = None
    api_error: bool = False
    result_text: str | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("result_text", None)
        return d


def _short(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _tool_hint(block: ToolUseBlock) -> str:
    inp = block.input or {}
    for key in ("command", "file_path", "pattern", "path"):
        if key in inp:
            return f"{block.name}: {_short(str(inp[key]), 100)}"
    return block.name


async def run_agent(
    *,
    stage: str,
    system_prompt: str,
    prompt: str,
    cwd: Path,
    tools: list[str],
    writable: list[Path],
    model: str,
    effort: str,
    max_turns: int,
    max_budget_usd: float,
    log_path: Path,
    gate: StopGate | None = None,
    env: dict[str, str] | None = None,
    protected: list[Path] | None = None,
    web_domains: list[str] | None = None,
    extra_secrets: list[str] | None = None,
) -> AgentRun:
    """한 단계의 에이전트 세션을 실행한다. 허용 목록 밖 도구는 묻지 않고 거부한다(dontAsk)."""
    hooks: dict[str, list[HookMatcher]] = {
        "PreToolUse": [
            HookMatcher(
                matcher="Bash|Write|Edit|MultiEdit|NotebookEdit|Read|Grep|Glob|WebFetch|WebSearch",
                hooks=[make_guard(cwd, writable, protected, list((env or {}).values()) + (extra_secrets or []),
                                  web_domains)],
            )
        ],
    }
    if gate is not None:
        hooks["Stop"] = [HookMatcher(hooks=[gate], timeout=GATE_HOOK_TIMEOUT_S)]

    options = ClaudeAgentOptions(
        cwd=str(cwd),
        model=model,
        effort=effort,  # type: ignore[arg-type]
        system_prompt=system_prompt,
        tools=tools,
        allowed_tools=tools,
        permission_mode="dontAsk",
        max_turns=max_turns,
        max_budget_usd=max_budget_usd,
        setting_sources=[],
        hooks=hooks,  # type: ignore[arg-type]
        env={**(env or {}), **SESSION_ENV},
        max_buffer_size=SESSION_BUFFER_BYTES,
    )

    log_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    result: ResultMessage | None = None
    error: str | None = None
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"# {stage}\n## system\n{system_prompt}\n## prompt\n{prompt}\n## transcript\n")
        try:
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock) and block.text.strip():
                            print(f"  [{stage}] {_short(block.text)}", flush=True)
                            log.write(f"\n[text] {block.text}\n")
                        elif isinstance(block, ToolUseBlock):
                            print(f"  [{stage}] -> {_tool_hint(block)}", flush=True)
                            log.write(f"\n[tool] {block.name} {json.dumps(block.input, ensure_ascii=False)[:2000]}\n")
                elif isinstance(message, ResultMessage):
                    result = message
                    log.write(f"\n[result] {message.subtype} cost={message.total_cost_usd} turns={message.num_turns}\n")
        except ClaudeSDKError as e:
            error = f"{type(e).__name__}: {e}"
            log.write(f"\n[error] {error}\n")

    duration = time.monotonic() - start
    if result is None:
        return AgentRun(stage, False, "no_result", 0.0, 0, duration, error=error or "결과 메시지를 받지 못했다",
                        gate=gate.stats() if gate else None)
    return AgentRun(
        stage=stage,
        ok=not result.is_error and error is None,
        subtype=result.subtype,
        cost_usd=result.total_cost_usd or 0.0,
        turns=result.num_turns,
        duration_s=duration,
        session_id=result.session_id,
        error=error or ("; ".join(map(str, result.errors)) if result.errors else None),
        gate=gate.stats() if gate else None,
        # subtype은 success인데 is_error면 모델이 일을 하지 못하고 API 오류(인증, 크레딧 등)로 끝난 것
        api_error=result.is_error and result.subtype == "success",
        result_text=result.result,
    )
