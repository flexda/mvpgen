"""Stop hook 게이트: 에이전트가 끝내려 할 때 검사기를 돌리고, 실패하면 멈추지 못하게 한다."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

Checker = Callable[[], tuple[bool, str]]


class StopGate:
    """검사 실패 시 {"decision": "block"}으로 같은 세션에서 계속 고치게 한다.

    max_blocks번 막은 뒤에는 더 막지 않고 종료를 허용한다. 최종 판정은 파이프라인이 다시 검사한다.
    """

    def __init__(self, name: str, checker: Checker, max_blocks: int = 3) -> None:
        self.name = name
        self.checker = checker
        self.max_blocks = max_blocks
        self.blocks = 0
        self.checks = 0
        self.last_ok: bool | None = None
        self.last_report = ""

    async def __call__(self, input_data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
        self.checks += 1
        ok, report = await asyncio.to_thread(self.checker)
        self.last_ok, self.last_report = ok, report
        if ok:
            return {}
        if self.blocks >= self.max_blocks:
            return {"systemMessage": f"[{self.name}] 검사 실패가 {self.max_blocks}회 반복되어 종료를 허용한다"}
        self.blocks += 1
        return {
            "decision": "block",
            "reason": (
                f"[자동 검사 실패 {self.blocks}/{self.max_blocks}] {self.name} 검사를 통과하지 못했다. "
                "아래 결과를 보고 원인을 고친 다음 작업을 마쳐라.\n\n"
                f"{report}"
            ),
        }

    def stats(self) -> dict[str, Any]:
        return {"checks": self.checks, "blocks": self.blocks, "last_ok": self.last_ok}
