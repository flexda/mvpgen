"""Design 단계: 디자인 라이브러리에서 후보를 무작위로 뽑고, 산출물(concepts.json, DESIGN.md)을 검사한다."""

from __future__ import annotations

import json
import random
import re
import shutil
from pathlib import Path

CANDIDATES_DIRNAME = "design-candidates"
DESIGN_HEADINGS = ("## Overview", "## Colors", "## Typography", "## Layout", "## Components", "## Responsive Behavior")
DESIGN_MIN_CHARS = 2000
DIRECTION_KINDS = ("baseline", "unexpected")
PREVIEWS_DIRNAME = "previews"
MIN_CONTRAST = 4.5
# DESIGN.md 프런트매터에서 본문 글자색과 배경색으로 볼 이름. 생성한 문서는 text와 background를 쓴다
TEXT_ROLES = ("text", "ink", "on-surface", "on-background", "body")
BACKGROUND_ROLES = ("background", "canvas", "surface", "paper")
HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
# 미리보기가 밖의 리소스를 부르는 자리: src/href 속성, CSS url(), @import
EXTERNAL_REF = re.compile(r"""(?:(?:src|href)\s*=\s*["']?\s*|url\(\s*["']?\s*)(?:https?:)?//|@import""", re.IGNORECASE)


def _channel(c: int) -> float:
    v = c / 255
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG 2 대비. #rgb 또는 #rrggbb."""
    def luminance(h: str) -> float:
        h = h.lstrip("#")
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        r, g, b = (_channel(int(h[i:i + 2], 16)) for i in (0, 2, 4))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    hi, lo = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _contrast_problem(where: str, text: object, background: object) -> str | None:
    if not (isinstance(text, str) and HEX.match(text) and isinstance(background, str) and HEX.match(background)):
        return f"{where}에 hex 값인 text와 background 색이 있어야 한다 (지금 text={text!r}, background={background!r})"
    ratio = contrast_ratio(text, background)
    if ratio < MIN_CONTRAST:
        return f"{where}의 본문 대비가 {ratio:.2f}:1이다. {MIN_CONTRAST}:1 이상이 되게 text나 background를 바꿔라"
    return None


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


def _load_concepts(path: Path) -> tuple[dict | None, list[str]]:
    if not path.exists():
        return None, ["concepts.json이 없다"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return None, [f"concepts.json이 올바른 JSON이 아니다: {e}"]
    if not isinstance(data, dict):
        return None, ["concepts.json은 객체여야 한다"]
    return data, []


def check_directions(path: Path, candidates: list[str]) -> list[str]:
    """방향 3개(사람이 고르기 전)를 검사한다. chosen은 보지 않는다."""
    data, problems = _load_concepts(path)
    if data is None:
        return problems
    directions = data.get("directions")
    if not isinstance(directions, list) or len(directions) != 3:
        return ["concepts.json의 directions는 방향 3개짜리 목록이어야 한다 (baseline 1개, unexpected 2개)"]
    kinds = [str(d.get("kind")) if isinstance(d, dict) else "" for d in directions]
    if sorted(kinds) != ["baseline", "unexpected", "unexpected"]:
        problems.append(f"directions의 kind는 baseline 1개와 unexpected 2개여야 한다 (지금: {kinds})")
    ids = [str(d.get("id", "")) for d in directions if isinstance(d, dict)]
    if len(set(ids)) != len(ids) or "" in ids:
        problems.append(f"directions의 id는 비어 있지 않고 서로 달라야 한다 (지금: {ids})")
    for d in directions:
        if not isinstance(d, dict):
            continue
        did = str(d.get("id", ""))
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
        colors = d.get("colors") if isinstance(d.get("colors"), dict) else {}
        problem = _contrast_problem(f"방향 {did}의 colors", colors.get("text"), colors.get("background"))
        if problem:
            problems.append(problem)
    return problems


def check_previews(run_dir: Path, direction_ids: list[str], feature_ids: list[str]) -> list[str]:
    """방향마다 previews/<id>.html이 있고, 밖의 리소스를 부르지 않고, 기능마다 data-feature 요소가 있는지 본다."""
    problems: list[str] = []
    for did in direction_ids:
        path = run_dir / PREVIEWS_DIRNAME / f"{did}.html"
        name = f"{PREVIEWS_DIRNAME}/{did}.html"
        if not path.exists():
            problems.append(f"{name}이 없다")
            continue
        html = path.read_text(encoding="utf-8")
        if EXTERNAL_REF.search(html):
            problems.append(f"{name}이 외부 리소스(http, //, @import)를 부른다. 글꼴, 이미지, CSS를 모두 파일 안에 둬라")
        missing = [f for f in feature_ids if not re.search(rf"""data-feature\s*=\s*["']{re.escape(f)}["']""", html)]
        if missing:
            problems.append(f"{name}에 기능 {', '.join(missing)}을 보여 주는 data-feature 요소가 없다")
    return problems


def directions_of(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["directions"]


def choose_direction(path: Path, direction_id: str, reason: str | None) -> dict:
    """사람이 고른 방향을 concepts.json에 적고 그 방향을 돌려준다. 없는 id면 ValueError."""
    data = json.loads(path.read_text(encoding="utf-8"))
    chosen = next((d for d in data["directions"] if str(d.get("id")) == direction_id), None)
    if chosen is None:
        ids = ", ".join(str(d.get("id")) for d in data["directions"])
        raise ValueError(f"{direction_id!r}는 방향 id가 아니다. 가능한 값: {ids}")
    data.update(chosen=direction_id, reason=reason or "", chosen_by="human")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return chosen


def check_concepts(path: Path, candidates: list[str]) -> list[str]:
    """방향 검사에 더해 chosen이 방향 id 중 하나인지 본다. baseline을 골라도 된다(사람이 고른다)."""
    problems = check_directions(path, candidates)
    if problems:
        return problems
    data = json.loads(path.read_text(encoding="utf-8"))
    if str(data.get("chosen", "")) not in {str(d.get("id")) for d in data["directions"]}:
        problems.append("chosen이 directions의 id 중 하나가 아니다")
    return problems


def front_colors(text: str) -> dict[str, str]:
    """DESIGN.md 프런트매터의 colors 블록(두 칸 들여쓴 name: "#hex")을 읽는다. 없으면 빈 dict."""
    front = text.split("---", 2)
    if not text.startswith("---") or len(front) < 3 or "colors:" not in front[1]:
        return {}
    colors: dict[str, str] = {}
    for line in front[1].split("colors:", 1)[1].splitlines()[1:]:
        m = re.match(r"""^  ([\w-]+):\s*["']?([^"'\s]+)["']?\s*$""", line)
        if not m:
            if line.strip() and not line.startswith("  "):
                break
            continue
        colors[m.group(1)] = m.group(2)
    return colors


def design_contrast(text: str, strict: bool) -> list[str]:
    """프런트매터 colors의 본문 대비를 본다. strict면 text와 background 이름을 요구하고,
    아니면(지정한 파일) 흔한 이름에서 찾고 못 찾으면 그렇다고 알린다."""
    colors = front_colors(text)
    if strict:
        problem = _contrast_problem("DESIGN.md 프런트매터 colors", colors.get("text"), colors.get("background"))
        return [problem] if problem else []
    fg = next((colors[r] for r in TEXT_ROLES if r in colors), None)
    bg = next((colors[r] for r in BACKGROUND_ROLES if r in colors), None)
    if fg is None or bg is None:
        return [f"colors에서 본문 글자색({'/'.join(TEXT_ROLES)})과 배경색({'/'.join(BACKGROUND_ROLES)})을 찾지 못해 대비를 확인하지 못했다"]
    problem = _contrast_problem("DESIGN.md 프런트매터 colors", fg, bg)
    return [problem] if problem else []


def check_design_md(path: Path, strict: bool = True) -> list[str]:
    """strict는 파이프라인이 만든 DESIGN.md, 아니면 사람이 지정한 파일이다."""
    if not path.exists():
        return ["DESIGN.md가 없다"]
    text = path.read_text(encoding="utf-8")
    problems: list[str] = []
    if not front_colors(text):
        problems.append("DESIGN.md 맨 앞에 colors 토큰이 있는 YAML 프런트매터(--- ... ---)가 없다")
    else:
        problems += design_contrast(text, strict)
    missing = [h for h in DESIGN_HEADINGS if h not in text]
    if missing:
        problems.append(f"DESIGN.md에 제목이 빠졌다: {', '.join(missing)}")
    if len(text) < DESIGN_MIN_CHARS:
        problems.append(f"DESIGN.md가 너무 짧다 ({len(text)}자, 최소 {DESIGN_MIN_CHARS}자)")
    return problems


def check_design(run_dir: Path, candidates: list[str]) -> list[str]:
    """Design 산출물을 검사해 문제 목록을 돌려준다. 빈 목록이면 통과."""
    return check_concepts(run_dir / "concepts.json", candidates) + check_design_md(run_dir / "DESIGN.md")
