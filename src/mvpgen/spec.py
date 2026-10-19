"""PRD와 Spec 단계 산출물(PRD.md, spec-candidates/, spec.json)의 스키마와 객관적 검사."""

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


class Intent(BaseModel):
    """아이디어 원문에서 뽑은 요구 하나와, 이를 해결하는 feature."""

    requirement: str = Field(..., min_length=1)
    feature_ids: list[str] = Field(..., min_length=1)


class Spec(BaseModel):
    name: str = Field(..., min_length=1)
    summary: str = Field(..., min_length=1)
    stack: str = Field(..., min_length=1)
    # 이 필드가 생기기 전의 spec도 읽을 수 있게 선택 항목으로 둔다. 새 Spec 단계는 검사기가 요구한다
    intent: list[Intent] | None = None
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
        unknown_intent = {fid for i in self.intent or [] for fid in i.feature_ids} - set(feature_ids)
        if unknown_intent:
            raise ValueError(f"intent가 존재하지 않는 feature를 가리킨다: {sorted(unknown_intent)}")
        return self


def load_spec(path: Path) -> Spec:
    return Spec.model_validate_json(path.read_text(encoding="utf-8"))


def check_prd(run_dir: Path) -> list[str]:
    """PRD.md를 검사해 문제 목록을 돌려준다. 빈 목록이면 통과."""
    prd_path = run_dir / "PRD.md"
    if not prd_path.exists():
        return ["PRD.md가 없다"]
    prd = prd_path.read_text(encoding="utf-8")
    problems: list[str] = []
    missing = [h for h in PRD_HEADINGS if h not in prd]
    if missing:
        problems.append(f"PRD.md에 필수 제목이 없다: {missing}")
    if len(prd) < PRD_MIN_CHARS:
        problems.append(f"PRD.md가 너무 짧다 ({len(prd)}자, 최소 {PRD_MIN_CHARS}자)")
    return problems


def _spec_problems(data: object, name: str) -> list[str]:
    try:
        spec = Spec.model_validate(data)
    except ValidationError as e:
        return [f"{name} 스키마 오류:\n{e}"]
    if not spec.intent:
        return [f"{name}에 intent가 없다. 요구 원문의 요구를 빠짐없이 나눠 적고 각각 feature id를 연결하라"]
    return []


def _read_json(path: Path) -> tuple[object, list[str]]:
    if not path.exists():
        return None, [f"{path.name}이 없다"]
    try:
        return json.loads(path.read_text(encoding="utf-8")), []
    except json.JSONDecodeError as e:
        return None, [f"{path.name}이 올바른 JSON이 아니다: {e}"]


def check_spec(run_dir: Path) -> list[str]:
    """고른 spec.json을 검사한다."""
    data, problems = _read_json(run_dir / "spec.json")
    return problems or _spec_problems(data, "spec.json")


def candidate_ids(cand_dir: Path) -> list[str]:
    return sorted(p.stem for p in cand_dir.glob("*.json"))


def check_spec_candidates(cand_dir: Path, n: int) -> list[str]:
    """spec-candidates/<id>.json 후보 n개를 검사한다. 후보는 {"decision", "approach", "spec"} 객체다.
    기능은 PRD를 따르므로 모든 후보의 feature id가 같아야 하고, approach는 서로 달라야 한다."""
    ids = candidate_ids(cand_dir)
    if len(ids) != n:
        return [f"{cand_dir.name}/에 후보 JSON이 {n}개 있어야 한다 (지금 {len(ids)}개: {ids})"]
    problems: list[str] = []
    feature_sets: dict[str, list[str]] = {}
    smoke_kinds: dict[str, str] = {}
    approaches: dict[str, str] = {}
    for cid in ids:
        name = f"{cand_dir.name}/{cid}.json"
        data, errs = _read_json(cand_dir / f"{cid}.json")
        if errs or not isinstance(data, dict):
            problems += errs or [f"{name}은 객체여야 한다"]
            continue
        for key in ("decision", "approach"):
            if not str(data.get(key, "")).strip():
                problems.append(f"{name}에 {key}가 비어 있다")
        approaches[cid] = str(data.get("approach", "")).strip()
        errs = _spec_problems(data.get("spec"), f"{name}의 spec")
        problems += errs
        if not errs:
            feature_sets[cid] = sorted(f["id"] for f in data["spec"]["features"])
            smoke_kinds[cid] = "url" if data["spec"]["smoke"].get("url") else "command"
    if len(set(map(tuple, feature_sets.values()))) > 1:
        problems.append(f"후보마다 feature id가 다르다 {feature_sets}. 기능은 PRD.md를 따라 모든 후보가 같아야 한다")
    if len(set(smoke_kinds.values())) > 1:
        # 화면이 있는 앱인지(디자인 단계를 돌릴지)는 사람이 고르기 전에 정해야 한다
        problems.append(f"후보마다 smoke 종류가 다르다 {smoke_kinds}. 모두 url(화면 있는 앱)이거나 모두 command여야 한다")
    if len(set(approaches.values())) != len(approaches):
        problems.append("후보의 approach가 서로 같다. decision 축에서 서로 다른 선택을 하라")
    return problems


def candidates_have_screen(cand_dir: Path) -> bool:
    """검사를 통과한 후보들이 화면(smoke.url)이 있는 앱인가. 후보끼리 smoke 종류가 같으므로 하나만 본다."""
    first = candidate_ids(cand_dir)[0]
    return bool(candidate_spec(cand_dir, first)["smoke"].get("url"))


def candidate(cand_dir: Path, cid: str) -> dict:
    return json.loads((cand_dir / f"{cid}.json").read_text(encoding="utf-8"))


def candidate_spec(cand_dir: Path, cid: str) -> dict:
    return json.loads((cand_dir / f"{cid}.json").read_text(encoding="utf-8"))["spec"]
