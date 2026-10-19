"""데이터 파이프라인 모드의 Plan 산출물(pipeline.json, PIPELINE.md) 스키마와 객관적 검사."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, model_validator

# 에이전트가 만들 수 있는 스키마. 이 밖의 스키마(public, auth, storage 등)는 건드리지 못한다
LAYERS = ("raw", "core", "mart")
PIPELINE_HEADINGS = ("## Source", "## Model", "## Load", "## Quality", "## Out of scope")
PIPELINE_MIN_CHARS = 300
_TABLE_NAME = re.compile(r"^(raw|core|mart)\.[a-z_][a-z0-9_]*$")
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")


_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
SAMPLE_PLACEHOLDERS = {"key", "page"}


class SampleRequest(BaseModel):
    """오케스트레이터가 Build 전에 대신 받아 둘 샘플 요청. 값의 {key}는 API 키로, {page}는 페이지 번호로 바뀐다."""

    url: str = Field(..., pattern=r"^https?://")
    params: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    pages: int = Field(2, ge=1, le=3)

    def texts(self) -> list[str]:
        return [self.url, *self.params.values(), *self.headers.values()]

    @property
    def uses_key(self) -> bool:
        return any("{key}" in s for s in self.texts())

    @model_validator(mode="after")
    def _placeholders(self) -> SampleRequest:
        unknown = {m for s in self.texts() for m in _PLACEHOLDER.findall(s)} - SAMPLE_PLACEHOLDERS
        if unknown:
            raise ValueError(f"sample에 알 수 없는 자리표시자가 있다: {sorted(unknown)}. {{key}}, {{page}}만 쓴다")
        return self


class Source(BaseModel):
    name: str = Field(..., min_length=1)
    endpoint: str = Field(..., min_length=1)
    # 키가 필요 없는 API면 null
    key_env: str | None = None
    doc: str = Field(..., min_length=1, description="참고한 context/ 안 문서 경로")
    sample: SampleRequest

    @model_validator(mode="after")
    def _sample_key(self) -> Source:
        if self.key_env and not self.sample.uses_key:
            raise ValueError("key_env가 있으면 sample의 url, params, headers 중 하나에 {key}를 넣어야 한다")
        if not self.key_env and self.sample.uses_key:
            raise ValueError("key_env가 없는데 sample에 {key}가 있다")
        return self


class Table(BaseModel):
    name: str = Field(..., description="schema.table, schema는 raw, core, mart 중 하나")
    description: str = Field(..., min_length=1)
    # True면 같은 데이터로 두 번 적재했을 때 행 수가 같아야 한다. 실행마다 쌓이는 raw 로그 테이블은 False
    idempotent: bool = True

    @property
    def layer(self) -> str:
        return self.name.split(".", 1)[0]

    @model_validator(mode="after")
    def _name(self) -> Table:
        if not _TABLE_NAME.match(self.name):
            raise ValueError(f"테이블 이름 {self.name!r}는 raw|core|mart.<소문자_이름> 형식이어야 한다")
        return self


class Check(BaseModel):
    """품질 검사. sql은 규칙을 어긴 행을 돌려주는 SELECT이고, 0행이면 통과다."""

    id: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    sql: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def _select_only(self) -> Check:
        if not re.match(r"^\s*(select|with)\b", self.sql, re.IGNORECASE):
            raise ValueError(f"check {self.id}의 sql은 SELECT 또는 WITH로 시작해야 한다")
        return self


class DataIntent(BaseModel):
    """목표 원문에서 뽑은 요구 하나와, 이를 해결하는 테이블 이름 또는 check id."""

    requirement: str = Field(..., min_length=1)
    covered_by: list[str] = Field(..., min_length=1)


class DataSpec(BaseModel):
    name: str = Field(..., min_length=1)
    summary: str = Field(..., min_length=1)
    source: Source
    intent: list[DataIntent] = Field(..., min_length=1)
    tables: list[Table] = Field(..., min_length=1)
    checks: list[Check] = Field(..., min_length=1)
    install_cmd: str | None = None
    test_cmd: str = Field(..., min_length=1)
    ingest_cmd: str = Field(..., min_length=1)
    # 자동 검사가 이 환경변수로 수집 페이지 수를 제한한다. 0이면 전체
    page_cap_env: str = "INGEST_MAX_PAGES"
    ingest_timeout: int = Field(600, ge=30, le=3600)

    @model_validator(mode="after")
    def _refs(self) -> DataSpec:
        names = [t.name for t in self.tables]
        if len(set(names)) != len(names):
            raise ValueError("테이블 이름이 중복된다")
        missing_layers = {"raw", "core"} - {t.layer for t in self.tables}
        if missing_layers:
            raise ValueError(f"{sorted(missing_layers)} 계층의 테이블이 없다")
        ids = [c.id for c in self.checks]
        if len(set(ids)) != len(ids):
            raise ValueError("check id가 중복된다")
        unknown = {r for i in self.intent for r in i.covered_by} - set(names) - set(ids)
        if unknown:
            raise ValueError(f"intent가 없는 테이블이나 check를 가리킨다: {sorted(unknown)}")
        for env in (self.page_cap_env, self.source.key_env):
            if env is not None and not _ENV_NAME.match(env):
                raise ValueError(f"환경변수 이름 {env!r}는 대문자, 숫자, 밑줄만 쓴다")
        return self


def load_data_spec(path: Path) -> DataSpec:
    return DataSpec.model_validate_json(path.read_text(encoding="utf-8"))


def check_data_plan(run_dir: Path, env_keys: list[str]) -> list[str]:
    """데이터 Plan 산출물을 검사해 문제 목록을 돌려준다. 빈 목록이면 통과."""
    problems: list[str] = []

    spec_path = run_dir / "pipeline.json"
    if not spec_path.exists():
        problems.append("pipeline.json이 없다")
    else:
        try:
            json.loads(spec_path.read_text(encoding="utf-8"))
            spec = load_data_spec(spec_path)
            if spec.source.key_env and spec.source.key_env not in env_keys:
                problems.append(f"source.key_env {spec.source.key_env}가 준비된 환경변수에 없다: {env_keys or '없음'}")
            if not (run_dir / spec.source.doc).is_file():
                problems.append(f"source.doc {spec.source.doc}가 없다. context/ 안의 실제 문서 경로를 적어라")
        except json.JSONDecodeError as e:
            problems.append(f"pipeline.json이 올바른 JSON이 아니다: {e}")
        except ValidationError as e:
            problems.append(f"pipeline.json 스키마 오류:\n{e}")

    doc_path = run_dir / "PIPELINE.md"
    if not doc_path.exists():
        problems.append("PIPELINE.md가 없다")
    else:
        doc = doc_path.read_text(encoding="utf-8")
        missing = [h for h in PIPELINE_HEADINGS if h not in doc]
        if missing:
            problems.append(f"PIPELINE.md에 필수 제목이 없다: {missing}")
        if len(doc) < PIPELINE_MIN_CHARS:
            problems.append(f"PIPELINE.md가 너무 짧다 ({len(doc)}자, 최소 {PIPELINE_MIN_CHARS}자)")

    return problems
