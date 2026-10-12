"""PreToolUse hook: 위험한 Bash 명령과 허용 범위 밖 파일 쓰기를 막는다."""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import Any

DENY_PATTERNS: list[tuple[str, str]] = [
    (r"(^|[\s;&|(])sudo\b", "sudo는 쓸 수 없다"),
    (r"\brm\s+(-\w+\s+)*(/|~|\$HOME)(\s|$|/\*)", "루트나 홈 디렉토리 삭제는 금지된다"),
    (r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba|z)?sh\b", "원격 스크립트를 셸로 바로 실행할 수 없다"),
    (r"\bmkfs\b|\bdd\s+if=", "디스크를 다루는 명령은 금지된다"),
    (r":\(\)\s*\{", "fork bomb은 금지된다"),
    (r"\bgit\s+push\b", "외부 저장소로 push할 수 없다"),
    (r"\b(shutdown|reboot|halt)\b", "시스템 종료 명령은 금지된다"),
    (r"\bchmod\s+(-\w+\s+)*777\s+/", "시스템 경로 권한 변경은 금지된다"),
    (r"ANTHROPIC_IDENTITY_TOKEN|ACTIONS_ID_TOKEN_REQUEST", "인증용 ID 토큰에는 접근할 수 없다"),
]

# 쓰기 계열 명령. 이 명령의 인자로 작업 폴더 밖 절대경로가 오면 막는다.
WRITE_COMMANDS = {"rm", "mv", "cp", "chmod", "chown", "ln", "touch", "mkdir", "tee", "rmdir", "truncate"}
# 쓰기 대상이 되어도 괜찮은 바깥 경로
SAFE_OUTSIDE = ("/dev/null", "/tmp", "/private/tmp", "/var/folders", "/private/var/folders")


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _is_safe_outside(token: str) -> bool:
    return any(token == p or token.startswith(p + "/") for p in SAFE_OUTSIDE)


def check_command(command: str, root: Path) -> str | None:
    """막아야 하면 이유를, 괜찮으면 None을 돌려준다."""
    for pattern, reason in DENY_PATTERNS:
        if re.search(pattern, command):
            return reason

    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()

    # 리다이렉션 대상 검사: > /abs/path, >> ~/x
    for m in re.finditer(r">{1,2}\s*([^\s;&|]+)", command):
        target = m.group(1).strip("'\"")
        if target.startswith("&"):
            continue
        if target.startswith(("/", "~")) and not _is_safe_outside(target):
            if not _is_within(Path(target).expanduser(), root):
                return f"작업 폴더 밖으로 출력을 쓸 수 없다: {target}"

    in_write_cmd = False
    for tok in tokens:
        if tok in {";", "&&", "||", "|"}:
            in_write_cmd = False
            continue
        base = Path(tok).name
        if base in WRITE_COMMANDS:
            in_write_cmd = True
            continue
        if in_write_cmd and tok.startswith(("/", "~")) and not _is_safe_outside(tok):
            if not _is_within(Path(tok).expanduser(), root):
                return f"작업 폴더 밖 경로를 바꿀 수 없다: {tok}"
    return None


def check_write(file_path: str, root: Path, writable: list[Path]) -> str | None:
    path = Path(file_path)
    if not path.is_absolute():
        path = root / path
    if not _is_within(path, root):
        return f"작업 폴더 밖에는 파일을 쓸 수 없다: {file_path}"
    if writable and not any(path.resolve() == w.resolve() or _is_within(path, w) for w in writable):
        allowed = ", ".join(str(w.relative_to(root)) if _is_within(w, root) else str(w) for w in writable)
        return f"이 단계에서는 다음 위치에만 쓸 수 있다: {allowed}"
    return None


def check_protected(paths: list[str], root: Path, protected: list[Path]) -> str | None:
    """protected 디렉토리(예: secrets/) 안을 가리키는 경로가 있으면 이유를 돌려준다."""
    for raw in paths:
        if not raw:
            continue
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = root / p
        if any(_is_within(p, d) for d in protected):
            return "비밀값 폴더에는 접근할 수 없다. 키는 환경변수로만 읽어라"
    return None


def check_secret_values(text: str, secret_values: list[str]) -> str | None:
    for value in secret_values:
        if value and value in text:
            return "비밀값을 코드, 파일, 명령에 직접 쓸 수 없다. 환경변수 이름으로 읽어라"
    return None


def _deny(input_data: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": input_data["hook_event_name"],
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def make_guard(
    root: Path,
    writable: list[Path],
    protected: list[Path] | None = None,
    secret_values: list[str] | None = None,
):
    """root 밖 쓰기, writable 밖 쓰기, protected 폴더 접근, 비밀값 직접 기입을 막는 PreToolUse 콜백."""
    protected = protected or []
    secrets = [v for v in (secret_values or []) if len(v) >= 8]

    async def guard(input_data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
        tool = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {}) or {}
        reason: str | None = None
        if tool == "Bash":
            command = str(tool_input.get("command", ""))
            try:
                tokens = shlex.split(command)
            except ValueError:
                tokens = command.split()
            reason = (
                check_command(command, root)
                or check_protected(tokens, root, protected)
                or check_secret_values(command, secrets)
            )
        elif tool in {"Write", "Edit", "MultiEdit", "NotebookEdit"}:
            target = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
            reason = check_write(str(target), root, writable) or check_secret_values(
                json.dumps(tool_input, ensure_ascii=False), secrets
            )
        elif tool in {"Read", "Grep", "Glob"}:
            reason = check_protected(
                [str(tool_input.get(k, "")) for k in ("file_path", "path", "pattern")], root, protected
            )
        return _deny(input_data, reason) if reason else {}

    return guard
