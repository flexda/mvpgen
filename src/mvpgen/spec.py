"""Plan 단계 산출물(spec.json, PRD.md)의 스키마와 객관적 검사."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, model_validator

PRD_HEADINGS = ("## Problem", "## Users", "## Features", "## Out of scope")
PRD_MIN_CHARS = 300


class Smoke(BaseModel):
    """앱이 떠 있는지 확인하는 방법. url 또는 command 중 하나만 쓴다."""

    url: str | None = Field(None, description="'{port}' 자리표시자를 쓸 수 있는 HTTP GET 주소")
    command: str | None = Field(None, description="앱 디렉토리에서 실행할 셸 명령")
    expect: str = Field(..., min_length=1, description="응답 본문이나 stdout에 들어 있어야 하는 문자열")

    @model_validator(mode="after")
    def _exactly_one(self) -> Smoke:
        if (self.url is None) == (self.command is None):
            raise ValueError("smoke에는 url과 command 중 정확히 하나만 지정해야 한다")
        return self


class Feature(BaseModel):
    id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)


class Criterion(BaseModel):
    id: str = Field(..., min_length=1)
    feature_id: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)


class Spec(BaseModel):
    name: str = Field(..., min_length=1)
    summary: str = Field(..., min_length=1)
    stack: str = Field(..., min_length=1)
    features: list[Feature] = Field(..., min_length=1, max_length=10)
    acceptance_criteria: list[Criterion] = Field(..., min_length=1)
    install_cmd: str | None = None
    test_cmd: str = Field(..., min_length=1)
    run_cmd: str = Field(..., min_length=1)
    smoke: Smoke
    startup_timeout: int = Field(60, ge=5, le=600)

    @model_validator(mode="after")
    def _criteria_cover_features(self) -> Spec:
        feature_ids = [f.id for f in self.features]
        if len(set(feature_ids)) != len(feature_ids):
            raise ValueError("feature id가 중복된다")
        unknown = {c.feature_id for c in self.acceptance_criteria} - set(feature_ids)
        if unknown:
            raise ValueError(f"존재하지 않는 feature를 가리키는 기준: {sorted(unknown)}")
        uncovered = set(feature_ids) - {c.feature_id for c in self.acceptance_criteria}
        if uncovered:
            raise ValueError(f"완료 기준이 없는 feature: {sorted(uncovered)}")
        return self


def load_spec(path: Path) -> Spec:
    return Spec.model_validate_json(path.read_text(encoding="utf-8"))


def check_plan(run_dir: Path) -> list[str]:
    """Plan 산출물을 검사해 문제 목록을 돌려준다. 빈 목록이면 통과."""
    problems: list[str] = []

    spec_path = run_dir / "spec.json"
    if not spec_path.exists():
        problems.append("spec.json이 없다")
    else:
        try:
            json.loads(spec_path.read_text(encoding="utf-8"))
            load_spec(spec_path)
        except json.JSONDecodeError as e:
            problems.append(f"spec.json이 올바른 JSON이 아니다: {e}")
        except ValidationError as e:
            problems.append(f"spec.json 스키마 오류:\n{e}")

    prd_path = run_dir / "PRD.md"
    if not prd_path.exists():
        problems.append("PRD.md가 없다")
    else:
        prd = prd_path.read_text(encoding="utf-8")
        missing = [h for h in PRD_HEADINGS if h not in prd]
        if missing:
            problems.append(f"PRD.md에 필수 제목이 없다: {missing}")
        if len(prd) < PRD_MIN_CHARS:
            problems.append(f"PRD.md가 너무 짧다 ({len(prd)}자, 최소 {PRD_MIN_CHARS}자)")

    return problems
