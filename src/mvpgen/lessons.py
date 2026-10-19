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
    _write(path, existing + added)
    return len(added)


def merge_lessons(dst: Path, src: Path) -> int:
    """src에만 있는 항목을 dst 뒤에 붙인다. 실행 중에 dst가 바뀌었어도 양쪽 항목을 모두 살린다. 추가한 개수를 돌려준다."""
    existing = _entries(dst)
    seen = set(existing)
    added = [e for e in dict.fromkeys(_entries(src)) if e not in seen]
    if added:
        _write(dst, existing + added)
    return len(added)


def _write(path: Path, entries: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    kept = entries[-MAX_STORED:]
    path.write_text("# 이전 실행에서 critic이 지적한 문제\n\n" + "\n".join(kept) + "\n", encoding="utf-8")


def lessons_prompt(path: Path, *stages: str) -> str:
    """stages 중 하나로 기록된 교훈. 단계가 나뉘기 전 이름(plan)도 함께 넘길 수 있다."""
    entries = [e for e in _entries(path) if e.startswith(tuple(f"- [{s}]" for s in stages))][-MAX_INJECTED:]
    if not entries:
        return ""
    return "\n\n# 이전 실행에서 반복된 실수 (같은 실수를 하지 말 것)\n" + "\n".join(entries)
