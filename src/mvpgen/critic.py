"""critic 결과(review.json) 스키마, 합격 판정, 라운드별 스냅샷과 롤백."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

SNAPSHOT_IGNORE = shutil.ignore_patterns(
    "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".next", "dist", "build", "*.pyc"
)


class Issue(BaseModel):
    severity: Literal["critical", "major", "minor"]
    location: str = Field(..., min_length=1)
    problem: str = Field(..., min_length=1)
    fix: str = Field(..., min_length=1)


class Review(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    passed: bool = Field(..., alias="pass")
    score: int = Field(..., ge=0, le=100)
    summary: str = Field(..., min_length=1)
    issues: list[Issue] = Field(default_factory=list)
    # 후보 중 하나를 고르는 라운드에서만 쓴다. score와 issues는 이 후보 기준이다
    winner: str | None = None

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "critical")

    def feedback(self) -> str:
        if not self.issues:
            return self.summary
        lines = [f"critic 요약: {self.summary}", "", "고쳐야 할 문제:"]
        for n, i in enumerate(self.issues, 1):
            lines.append(f"{n}. [{i.severity}] {i.location}: {i.problem}\n   수정 방향: {i.fix}")
        return "\n".join(lines)


def load_review(path: Path) -> Review:
    return Review.model_validate_json(path.read_text(encoding="utf-8"))


def check_review_file(path: Path, winners: list[str] | None = None) -> tuple[bool, str]:
    """winners를 주면 review의 winner가 그중 하나여야 한다."""
    if not path.exists():
        return False, f"{path.name}이 아직 없다. 지정된 형식으로 작성하라."
    try:
        review = load_review(path)
    except ValidationError as e:
        return False, f"{path.name} 스키마 오류:\n{e}"
    if winners is not None and review.winner not in winners:
        return False, f"{path.name}의 winner가 후보 id 중 하나가 아니다 (지금 {review.winner!r}, 후보 {', '.join(winners)})"
    return True, "review 파일 확인"


def is_accepted(review: Review, threshold: int) -> bool:
    """critic이 pass라고 해도 점수 미달이거나 critical issue가 있으면 불합격."""
    return review.passed and review.score >= threshold and review.critical_count == 0


def snapshot(paths: list[Path], root: Path, dest: Path) -> None:
    """root 아래 paths(파일 또는 디렉토리)를 dest로 복사한다."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for p in paths:
        if not p.exists():
            continue
        target = dest / p.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        if p.is_dir():
            shutil.copytree(p, target, ignore=SNAPSHOT_IGNORE)
        else:
            shutil.copy2(p, target)


def restore(paths: list[Path], root: Path, src: Path) -> None:
    """snapshot의 역. 디렉토리는 무시 목록(node_modules 등)을 남긴 채 내용을 교체한다."""
    for p in paths:
        saved = src / p.relative_to(root)
        if not saved.exists():
            continue
        if saved.is_dir():
            if p.exists():
                for child in p.iterdir():
                    if SNAPSHOT_IGNORE(str(p), [child.name]):
                        continue
                    shutil.rmtree(child) if child.is_dir() else child.unlink()
            shutil.copytree(saved, p, dirs_exist_ok=True)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(saved, p)


@dataclass
class Best:
    round: int
    review: Review
    snapshot_dir: Path


class RoundTracker:
    """라운드마다 산출물을 저장하고, 가장 높은 점수의 라운드를 기억한다."""

    def __init__(self, paths: list[Path], root: Path, snap_root: Path) -> None:
        self.paths = paths
        self.root = root
        self.snap_root = snap_root
        self.best: Best | None = None

    def record(self, round_no: int, review: Review) -> bool:
        """이번 라운드를 기록한다. 직전 최고점보다 낮으면 최고점 산출물로 되돌리고 True를 돌려준다."""
        if self.best is not None and review.score < self.best.review.score:
            restore(self.paths, self.root, self.best.snapshot_dir)
            return True
        snap = self.snap_root / f"round-{round_no}"
        snapshot(self.paths, self.root, snap)
        self.best = Best(round_no, review, snap)
        return False

    def restore_best(self) -> None:
        if self.best is not None:
            restore(self.paths, self.root, self.best.snapshot_dir)
