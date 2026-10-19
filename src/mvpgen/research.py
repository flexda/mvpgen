"""Spec 후보별 조사 결과(research/<id>.md)의 형식 검사."""

from __future__ import annotations

from pathlib import Path

RESEARCH_DIRNAME = "research"
RESEARCH_HEADINGS = ("## 확인한 것", "## 위험", "## 출처")
RESEARCH_MIN_CHARS = 300


def check_research(path: Path) -> list[str]:
    """빈 목록이면 통과."""
    if not path.exists():
        return [f"{RESEARCH_DIRNAME}/{path.name}이 없다"]
    text = path.read_text(encoding="utf-8")
    problems: list[str] = []
    missing = [h for h in RESEARCH_HEADINGS if h not in text]
    if missing:
        problems.append(f"{RESEARCH_DIRNAME}/{path.name}에 제목이 빠졌다: {', '.join(missing)}")
    if len(text) < RESEARCH_MIN_CHARS:
        problems.append(f"{RESEARCH_DIRNAME}/{path.name}이 너무 짧다 ({len(text)}자, 최소 {RESEARCH_MIN_CHARS}자)")
    return problems
