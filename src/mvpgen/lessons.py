"""critic이 지적한 문제를 실행 간에 누적해 다음 생성에 반영한다."""

from __future__ import annotations

from pathlib import Path

from mvpgen.critic import Issue

MAX_STORED = 200
MAX_INJECTED = 20


def _entries(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("- ")]


def record_lessons(path: Path, stage: str, issues: list[Issue]) -> int:
    """major 이상 issue를 기록한다. 이미 같은 문장이 있으면 건너뛴다. 추가한 개수를 돌려준다."""
    existing = _entries(path)
    seen = set(existing)
    added = []
    for i in issues:
        if i.severity == "minor":
            continue
        line = f"- [{stage}] {i.problem.strip()} -> {i.fix.strip()}".replace("\n", " ")
        if line not in seen:
            seen.add(line)
            added.append(line)
    if not added:
        return 0
    kept = (existing + added)[-MAX_STORED:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# 이전 실행에서 critic이 지적한 문제\n\n" + "\n".join(kept) + "\n", encoding="utf-8")
    return len(added)


def lessons_prompt(path: Path, stage: str) -> str:
    entries = [e for e in _entries(path) if e.startswith(f"- [{stage}]")][-MAX_INJECTED:]
    if not entries:
        return ""
    return "\n\n# 이전 실행에서 반복된 실수 (같은 실수를 하지 말 것)\n" + "\n".join(entries)
