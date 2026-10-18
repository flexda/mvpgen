"""Design 단계: 디자인 라이브러리에서 후보를 무작위로 뽑고, 산출물(concepts.json, DESIGN.md)을 검사한다."""

from __future__ import annotations

import json
import random
import shutil
from pathlib import Path

CANDIDATES_DIRNAME = "design-candidates"
DESIGN_HEADINGS = ("## Overview", "## Colors", "## Typography", "## Layout", "## Components", "## Responsive Behavior")
DESIGN_MIN_CHARS = 2000
DIRECTION_KINDS = ("baseline", "unexpected")


def list_library(library: Path) -> list[str]:
    """라이브러리에서 DESIGN.md가 있는 브랜드 이름 목록."""
    return sorted(p.parent.name for p in library.glob("*/DESIGN.md"))


def pick_candidates(library: Path, n: int, seed: int) -> list[str]:
    """seed가 같으면 같은 후보를 돌려준다. 이름 순으로 정렬해 돌려준다."""
    brands = list_library(library)
    return sorted(random.Random(seed).sample(brands, min(n, len(brands))))


def copy_candidates(library: Path, brands: list[str], run_dir: Path) -> list[str]:
    """후보 DESIGN.md를 run_dir/design-candidates/<brand>.md로 복사하고 실행 폴더 기준 경로를 돌려준다."""
    dst = run_dir / CANDIDATES_DIRNAME
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    paths = []
    for b in brands:
        shutil.copy2(library / b / "DESIGN.md", dst / f"{b}.md")
        paths.append(f"{CANDIDATES_DIRNAME}/{b}.md")
    return paths


def check_concepts(path: Path, candidates: list[str]) -> list[str]:
    if not path.exists():
        return ["concepts.json이 없다"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [f"concepts.json이 올바른 JSON이 아니다: {e}"]
    if not isinstance(data, dict):
        return ["concepts.json은 객체여야 한다"]

    problems: list[str] = []
    directions = data.get("directions")
    if not isinstance(directions, list) or len(directions) != 3:
        return ["concepts.json의 directions는 방향 3개짜리 목록이어야 한다 (baseline 1개, unexpected 2개)"]
    kinds = [str(d.get("kind")) if isinstance(d, dict) else "" for d in directions]
    if sorted(kinds) != ["baseline", "unexpected", "unexpected"]:
        problems.append(f"directions의 kind는 baseline 1개와 unexpected 2개여야 한다 (지금: {kinds})")
    by_id: dict[str, dict] = {}
    for d in directions:
        if not isinstance(d, dict):
            continue
        did = str(d.get("id", ""))
        by_id[did] = d
        sources = d.get("sources")
        if not isinstance(sources, list) or not sources:
            problems.append(f"방향 {did}에 sources(원천 브랜드 목록)가 없다")
            continue
        outside = [s for s in sources if s not in candidates]
        if outside:
            problems.append(f"방향 {did}의 sources {outside}는 후보에 없다. 후보: {', '.join(candidates)}")
        for key in ("metaphor", "first_screen", "risks"):
            if not str(d.get(key, "")).strip():
                problems.append(f"방향 {did}에 {key}가 비어 있다")

    chosen = by_id.get(str(data.get("chosen", "")))
    if chosen is None:
        problems.append("chosen이 directions의 id 중 하나가 아니다")
    elif chosen.get("kind") != "unexpected":
        problems.append("기준안(baseline)을 골랐다. unexpected 방향 중 하나를 골라라")
    if not str(data.get("reason", "")).strip():
        problems.append("reason(선택 이유)이 비어 있다")
    return problems


def check_design_md(path: Path) -> list[str]:
    if not path.exists():
        return ["DESIGN.md가 없다"]
    text = path.read_text(encoding="utf-8")
    problems: list[str] = []
    front = text.split("---", 2)
    if not text.startswith("---") or len(front) < 3 or "colors:" not in front[1]:
        problems.append("DESIGN.md 맨 앞에 colors 토큰이 있는 YAML 프런트매터(--- ... ---)가 없다")
    missing = [h for h in DESIGN_HEADINGS if h not in text]
    if missing:
        problems.append(f"DESIGN.md에 제목이 빠졌다: {', '.join(missing)}")
    if len(text) < DESIGN_MIN_CHARS:
        problems.append(f"DESIGN.md가 너무 짧다 ({len(text)}자, 최소 {DESIGN_MIN_CHARS}자)")
    return problems


def check_design(run_dir: Path, candidates: list[str]) -> list[str]:
    """Design 산출물을 검사해 문제 목록을 돌려준다. 빈 목록이면 통과."""
    return check_concepts(run_dir / "concepts.json", candidates) + check_design_md(run_dir / "DESIGN.md")
