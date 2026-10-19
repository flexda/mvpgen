"""단계 순서, 두 겹의 검증 루프, 상태 저장을 담당하는 오케스트레이터."""

from __future__ import annotations

import json
import random
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from mvpgen import prompts
from mvpgen.agents import AgentRun, run_agent
from mvpgen.context import BRIEF_NAME, list_context
from mvpgen.critic import RoundTracker, Review, Screening, check_review_file, check_screening_file, is_accepted, load_review, load_screening
from mvpgen.design import (PREVIEWS_DIRNAME, check_design, check_design_md, check_directions, check_previews, choose_direction,
                           copy_candidates, directions_of, list_library, write_index)
from mvpgen.gates import StopGate
from mvpgen.lessons import lessons_prompt, record_lessons
from mvpgen.research import RESEARCH_DIRNAME, check_research
from mvpgen.rubrics import BUILD_RUBRIC, PRD_RUBRIC, SPEC_RUBRIC
from mvpgen.spec import (Spec, candidate, candidate_ids, candidate_spec, candidates_have_screen, check_prd, check_spec,
                         check_spec_candidates, load_spec)
from mvpgen.verify import free_port, verify_app

@dataclass(frozen=True)
class Stage:
    """생성자 + critic 루프를 도는 단계 하나의 고정 설정."""

    name: str
    label: str  # Stop gate와 검사 메시지에 쓰는 이름
    gen_tools: tuple[str, ...]
    critic_tools: tuple[str, ...]
    rubric: str
    # critic이 앱을 띄워 볼 포트가 필요한가
    critic_port: bool = False
    # critic 루프를 도는가. design은 사람이 미리보기로 고르고 코드 검사만 하므로 critic이 없다
    reviewed: bool = True


# 실행 순서대로 둔다. 이 순서가 --stage-model 키와 README 검증 기록의 순서가 된다
STAGES: dict[str, Stage] = {s.name: s for s in (
    Stage("prd", "PRD", ("Read", "Write", "Edit", "Glob"), ("Read", "Glob", "Grep", "Write"), PRD_RUBRIC),
    Stage("spec", "Spec", ("Read", "Write", "Edit", "Glob"), ("Read", "Glob", "Grep", "Write"), SPEC_RUBRIC),
    Stage("design", "Design", ("Read", "Write", "Edit", "Glob", "Grep"), (), "", reviewed=False),
    Stage("build", "Build", ("Read", "Write", "Edit", "Glob", "Grep", "Bash"), ("Read", "Glob", "Grep", "Write", "Bash"),
          BUILD_RUBRIC, critic_port=True),
)}

# Spec 후보를 조사하는 세션의 도구. 쓰기는 자기 조사 파일 하나로 막고, 셸은 주지 않는다
RESEARCH_TOOLS = ("Read", "Glob", "Grep", "Write", "WebSearch", "WebFetch")

# 이 상태로 끝난 단계는 --resume에서 다시 돌리지 않는다
DONE_STATUSES = frozenset({"passed", "passed_with_issues"})


class BudgetExceeded(RuntimeError):
    pass


class StageFailed(RuntimeError):
    pass


class AwaitingChoice(RuntimeError):
    """사람이 고를 차례라 실행을 멈춘다. 실패가 아니다. --resume --choose-spec/--choose-design으로 이어 간다."""


# 단계가 prd와 spec으로 나뉘기 전 이름. --stage-model과 lessons.md의 plan 값을 두 단계가 이어 쓴다
LEGACY_STAGE = {"prd": "plan", "spec": "plan"}

# --stage-model에 쓸 수 있는 키. critic은 모든 critic에 적용되고, 개별 critic 키가 그보다 우선한다
STAGE_MODEL_KEYS = (*STAGES, "plan", "research", "critic", *(f"{n}-critic" for n, s in STAGES.items() if s.reviewed),
                    "plan-critic")


def model_for(stage: str, stage_models: dict[str, str], default: str) -> str:
    """세션 이름(prd, build-fix1, spec-critic 등)에 쓸 모델. build-fixN, design-directions는 앞 단계 설정을 따르고,
    spec-screen-critic은 spec-critic 설정을 따른다. prd와 spec은 따로 지정하지 않으면 plan 값을 쓴다."""
    if stage.endswith("-critic"):
        base = stage.removesuffix("-critic").split("-", 1)[0]
        legacy = LEGACY_STAGE.get(base)
        return (stage_models.get(stage) or stage_models.get(f"{base}-critic")
                or (legacy and stage_models.get(f"{legacy}-critic")) or stage_models.get("critic") or default)
    base = stage.split("-", 1)[0]
    if base == "research":
        # 조사 세션(research-a 등)은 따로 지정하지 않으면 spec 설정을 따른다
        return stage_models.get("research") or model_for("spec", stage_models, default)
    return stage_models.get(base) or stage_models.get(LEGACY_STAGE.get(base, "")) or default


def parse_stage_models(items: list[str]) -> dict[str, str]:
    """["plan=claude-sonnet-5-5", ...]를 {"plan": "claude-sonnet-5-5"}로 바꾼다. 형식이나 키가 틀리면 ValueError."""
    models: dict[str, str] = {}
    for item in items:
        key, sep, value = item.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not value:
            raise ValueError(f"{item!r}는 STAGE=MODEL 형식이어야 한다")
        if key not in STAGE_MODEL_KEYS:
            raise ValueError(f"{key!r}는 알 수 없는 단계다. 가능한 값: {', '.join(STAGE_MODEL_KEYS)}")
        if key in models:
            raise ValueError(f"{key}가 두 번 지정되었다")
        models[key] = value
    return models


class AgentAborted(RuntimeError):
    """세션이 작업을 시작하지 못하고 끝났다 (API 오류, CLI 실행 실패). 재시도해도 같은 결과가 나온다."""


@dataclass
class RunConfig:
    idea: str
    out_dir: Path
    model: str = "claude-opus-5-5"
    # 단계별 모델. 키는 STAGE_MODEL_KEYS, 없는 단계는 model을 쓴다
    stage_models: dict[str, str] = field(default_factory=dict)
    effort: str = "high"
    budget_usd: float = 10.0
    max_review_rounds: int = 2
    max_gate_blocks: int = 3
    max_fix_rounds: int = 2
    pass_threshold: int = 80
    plan_max_turns: int = 30  # prd와 spec 세션 각각
    # Spec 단계가 만들 구현 후보 수. critic이 그중 하나를 spec.json으로 고른다
    spec_candidates: int = 2
    # 후보마다 조사 세션(웹 검색 포함)을 돌려 research/<id>.md를 남기고 spec critic이 근거로 쓴다
    research: bool = True
    research_max_turns: int = 40
    design_max_turns: int = 60
    build_max_turns: int = 150
    critic_max_turns: int = 60
    protected_paths: list[Path] = field(default_factory=list)
    mvp_env: dict[str, str] = field(default_factory=dict)
    # 실행 간 교훈 파일. 없으면 out_dir/lessons.md
    lessons_path: Path | None = None
    # off: Design 단계 없음, auto: 라이브러리에서 무작위 후보를 뽑아 Design 에이전트가 방향을 정함, 그 밖: 그대로 쓸 DESIGN.md 경로
    design: str = "off"
    design_library: Path | None = None
    # 사람이 고른 구현 후보(spec)와 디자인 방향, 각각의 이유. 고를 차례에 멈춘 실행을 --resume으로 이어 갈 때 준다.
    # choose_spec="recommended"는 critic의 추천을 그대로 쓴다(멈추지 않는 실행용)
    choose_spec: str | None = None
    spec_reason: str | None = None
    choose_design: str | None = None
    design_reason: str | None = None


# 실행 설정 중 --resume에서 플래그를 생략하면 처음 실행의 값을 이어 쓰는 것과 그 기본값
SETTING_DEFAULTS: dict[str, Any] = {
    "model": "claude-opus-5-5", "stage_models": {}, "effort": "high", "budget_usd": 10.0, "design": "auto",
    "spec_candidates": 2, "research": True,
}


def resolve_settings(given: dict[str, Any], state: dict[str, Any] | None) -> dict[str, Any]:
    """given에서 None인 값(stage_models는 빈 dict)은 state에 저장된 값, 그것도 없으면 기본값을 쓴다.
    stage_models는 저장된 값 위에 given을 덮어쓴다."""
    saved: dict[str, Any] = {}
    if state is not None:
        # settings가 생기기 전의 state에도 model과 stage_models는 있다
        saved = {"model": state.get("model"), "stage_models": state.get("stage_models") or {}, **state.get("settings", {})}
    merged = {k: given.get(k) if given.get(k) is not None else saved.get(k, d) for k, d in SETTING_DEFAULTS.items()}
    merged["stage_models"] = {**saved.get("stage_models", {}), **(given.get("stage_models") or {})}
    return merged


def make_slug(idea: str, now: datetime | None = None) -> str:
    now = now or datetime.now()
    words = re.findall(r"[a-zA-Z0-9]+", idea.lower())[:4]
    tail = "-".join(words) or "mvp"
    return f"{now:%Y%m%d-%H%M%S}-{tail}"


NAME_SLUG_MAX = 40


def name_slug(name: str) -> str:
    """spec.name을 폴더 이름에 쓸 수 있게 영문 소문자, 숫자, 하이픈만 남긴다."""
    return "-".join(re.findall(r"[a-z0-9]+", name.lower()))[:NAME_SLUG_MAX].strip("-")


def fallback_stamp(slug: str) -> str | None:
    """아이디어에서 영문 단어를 못 뽑아 '<시각>-mvp'가 된 slug면 시각 부분을 돌려준다.
    'build-a-todo-mvp'처럼 아이디어에 mvp가 들어간 slug는 해당하지 않는다."""
    m = re.fullmatch(r"(\d{8}-\d{6})-mvp", slug)
    return m.group(1) if m else None


def find_run_dir(out_dir: Path, slug: str) -> Path | None:
    """slug 폴더를 찾는다. Spec 뒤에 이름이 바뀌었으면 renamed_from이 slug인 폴더를 돌려준다."""
    direct = out_dir / slug
    if (direct / "state.json").exists():
        return direct
    stamp = fallback_stamp(slug)
    if stamp is None:
        return None
    for cand in sorted(out_dir.glob(f"{stamp}-*/state.json")):
        if json.loads(cand.read_text(encoding="utf-8")).get("renamed_from") == slug:
            return cand.parent
    return None


class Pipeline:
    def __init__(self, config: RunConfig, run_dir: Path) -> None:
        self.config = config
        self.lessons_path = config.lessons_path or config.out_dir / "lessons.md"
        self._set_run_dir(run_dir)
        self.state: dict[str, Any] = self._load_state()
        # --resume이 플래그를 생략했을 때 이어 쓸 값. 마지막 실행의 설정을 남긴다
        self.state["settings"] = {"model": config.model, "stage_models": config.stage_models, "effort": config.effort,
                                  "budget_usd": config.budget_usd, "design": config.design,
                                  "spec_candidates": config.spec_candidates, "research": config.research}

    def _set_run_dir(self, run_dir: Path) -> None:
        # 모든 단계가 이 세 경로에서 파일 경로를 만든다. 폴더 이름을 바꾸면 여기서 한 번에 갱신한다
        self.run_dir = run_dir
        self.app_dir = run_dir / "app"
        self.state_path = run_dir / "state.json"

    def rename_after_spec(self) -> None:
        """아이디어에서 영문 slug를 못 만들어 '<시각>-mvp'가 된 폴더를 spec.name 기반 이름으로 바꾼다."""
        stamp = fallback_stamp(self.run_dir.name)
        if stamp is None or not (self.run_dir / "spec.json").exists():
            return
        tail = name_slug(load_spec(self.run_dir / "spec.json").name)
        if not tail or tail == "mvp":
            return
        old = self.run_dir.name
        new_dir = self.run_dir.with_name(f"{stamp}-{tail}")
        if new_dir.exists():
            print(f"폴더 이름 변경 생략: {new_dir.name}이 이미 있다", flush=True)
            return
        try:
            self.run_dir.rename(new_dir)
        except OSError as e:
            print(f"폴더 이름 변경 실패, 기존 이름으로 계속한다: {e}", flush=True)
            return
        self._set_run_dir(new_dir)
        self.state["renamed_from"] = old
        self._save()
        print(f"\n폴더 이름 변경: {old} -> {new_dir.name}\n폴더: {new_dir}", flush=True)

    # ---- 상태 ----
    def _load_state(self) -> dict[str, Any]:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        return {"idea": self.config.idea, "model": self.config.model, "stage_models": self.config.stage_models,
                "stages": {}, "runs": [], "cost_usd": 0.0}

    def _save(self) -> None:
        self.state_path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _stage(self, name: str) -> dict[str, Any]:
        return self.state["stages"].setdefault(name, {"status": "pending", "rounds": []})

    def _done(self, name: str, extra: frozenset[str] = frozenset()) -> bool:
        """이전 실행에서 끝난 단계면 알리고 True를 돌려준다."""
        status = self._stage(name)["status"]
        if status not in DONE_STATUSES | extra:
            return False
        print(f"{name}: 이전 실행 결과를 사용한다" + (f" ({status})" if extra else ""))
        return True

    def _gate(self, stage: Stage, check: Callable[[], tuple[bool, str]]) -> StopGate:
        return StopGate(stage.label, check, self.config.max_gate_blocks)

    @property
    def _has_brief(self) -> bool:
        return (self.run_dir / BRIEF_NAME).is_file()

    @property
    def awaiting_choice(self) -> bool:
        return self.state["stages"].get("choice", {}).get("status") == "awaiting_choice"

    @property
    def spent(self) -> float:
        return float(self.state["cost_usd"])

    def _remaining(self) -> float:
        left = self.config.budget_usd - self.spent
        if left <= 0.05:
            raise BudgetExceeded(f"예산 ${self.config.budget_usd:.2f}을 모두 썼다 (사용 ${self.spent:.2f})")
        return left

    def _record_run(self, run: AgentRun, round_no: int, model: str) -> None:
        self.state["cost_usd"] = self.spent + run.cost_usd
        self.state["runs"].append({**run.to_dict(), "round": round_no, "model": model})
        self._save()
        status = "완료" if run.ok else f"실패({run.subtype})"
        gate = f", gate block {run.gate['blocks']}회" if run.gate else ""
        print(f"  <- {run.stage} {status} ({model}): ${run.cost_usd:.3f}, {run.turns}턴{gate}, 누적 ${self.spent:.2f}", flush=True)

    async def _agent(self, *, stage: str, round_no: int, **kwargs: Any) -> AgentRun:
        model = model_for(stage, self.config.stage_models, self.config.model)
        run = await run_agent(
            stage=stage,
            cwd=self.run_dir,
            model=model,
            effort=self.config.effort,
            max_budget_usd=self._remaining(),
            log_path=self.run_dir / "logs" / f"{stage}-r{round_no}.log",
            env=self.config.mvp_env,
            protected=self.config.protected_paths,
            **kwargs,
        )
        self._record_run(run, round_no, model)
        if run.subtype == "error_max_budget_usd":
            raise BudgetExceeded("세션이 남은 예산을 모두 썼다")
        if run.api_error or run.subtype == "no_result":
            detail = run.result_text or run.error or run.subtype
            raise AgentAborted(f"{stage} 세션이 API 오류로 끝났다: {detail}")
        return run

    # ---- 검사기 ----
    @staticmethod
    def _report(problems: list[str], label: str) -> tuple[bool, str]:
        return (not problems), ("\n".join(f"- {p}" for p in problems) or f"{label} 검사 통과")

    def _prd_check(self) -> tuple[bool, str]:
        return self._report(check_prd(self.run_dir), "PRD")

    def _candidates_check(self) -> tuple[bool, str]:
        return self._report(check_spec_candidates(self.run_dir / "spec-candidates", self.config.spec_candidates), "Spec 후보")

    def _spec_check(self) -> tuple[bool, str]:
        return self._report(check_spec(self.run_dir), "Spec")

    def _design_check(self) -> tuple[bool, str]:
        problems = check_design(self.run_dir, self.state["design"]["candidates"])
        return (not problems), ("\n".join(f"- {p}" for p in problems) or "Design 검사 통과")

    def _build_check(self) -> tuple[bool, str]:
        result = verify_app(self.app_dir, load_spec(self.run_dir / "spec.json"), extra_env=self.config.mvp_env)
        return result.ok, result.report()

    # ---- 생성자 + 비평가 루프 ----
    async def _review_loop(
        self,
        spec: Stage,
        *,
        paths: list[Path],
        generate: Callable[[str | None, int], Any],
        check: Callable[[], tuple[bool, str]],
        fix: Callable[[str, int, int], Any] | None = None,
        initial_feedback: str | None = None,
    ) -> Review:
        """initial_feedback을 주면 1라운드 생성부터 그 지적을 반영한다(이미 있는 산출물을 고치는 경우)."""
        stage = spec.name
        info = self._stage(stage)
        tracker = RoundTracker(paths, self.run_dir, self.run_dir / "snapshots" / stage)
        feedback: str | None = initial_feedback
        last: Review | None = None

        for round_no in range(1, self.config.max_review_rounds + 2):
            print(f"\n== {stage} 라운드 {round_no}: 생성", flush=True)
            await generate(feedback, round_no)

            ok, report = check()
            fix_no = 0
            while not ok and fix is not None and fix_no < self.config.max_fix_rounds:
                fix_no += 1
                print(f"\n== {stage} 라운드 {round_no}: 검사 실패, 수정 세션 {fix_no}", flush=True)
                await fix(report, round_no, fix_no)
                ok, report = check()
            if not ok:
                info["status"] = "failed"
                info["last_check"] = report
                self._save()
                raise StageFailed(f"{stage} 단계가 자동 검사를 통과하지 못했다:\n{report}")

            print(f"\n== {stage} 라운드 {round_no}: critic 평가", flush=True)
            review_rel = f"reviews/{stage}-r{round_no}.json"
            review_path = self.run_dir / review_rel
            review_path.parent.mkdir(exist_ok=True)
            critic_gate = StopGate(f"{stage} review", lambda: check_review_file(review_path), self.config.max_gate_blocks)
            port = free_port() if spec.critic_port else None
            await self._agent(
                stage=f"{stage}-critic",
                round_no=round_no,
                system_prompt=prompts.CRITIC_SYSTEM,
                prompt=prompts.critic_prompt(stage, self.config.idea, spec.rubric, review_rel, port,
                                          has_context=bool(list_context(self.run_dir)),
                                          has_design=(self.run_dir / "DESIGN.md").exists(), has_brief=self._has_brief),
                tools=list(spec.critic_tools),
                writable=[review_path],
                max_turns=self.config.critic_max_turns,
                gate=critic_gate,
            )
            ok_file, msg = check_review_file(review_path)
            if not ok_file:
                raise StageFailed(f"{stage} critic이 유효한 review를 남기지 못했다: {msg}")
            review = load_review(review_path)
            accepted = is_accepted(review, self.config.pass_threshold)
            rolled_back = tracker.record(round_no, review)
            added = record_lessons(self.lessons_path, stage, review.issues)
            info["rounds"].append({
                "round": round_no, "score": review.score, "pass": review.passed, "accepted": accepted,
                "critical": review.critical_count, "issues": len(review.issues), "rolled_back": rolled_back,
                "lessons_added": added,
            })
            self._save()
            verdict = "합격" if accepted else "불합격"
            print(f"  critic: {review.score}점, {verdict}, issue {len(review.issues)}개"
                  + (", 점수 하락으로 이전 최고 라운드로 되돌림" if rolled_back else ""), flush=True)

            if accepted:
                info["status"] = "passed"
                self._save()
                return review
            if round_no > self.config.max_review_rounds:
                break
            best = tracker.best
            feedback = (best.review if rolled_back and best else review).feedback()
            last = review

        tracker.restore_best()
        info["status"] = "passed_with_issues"
        self._save()
        best = tracker.best
        print(f"  {stage}: 개정 한도에 도달해 최고점 라운드({best.round if best else '-'})로 진행한다", flush=True)
        return best.review if best else last  # type: ignore[return-value]

    # ---- 단계 ----
    async def prd(self) -> None:
        stage = STAGES["prd"]
        if self._done(stage.name):
            return
        system = prompts.PRD_SYSTEM + lessons_prompt(self.lessons_path, stage.name, LEGACY_STAGE[stage.name])
        writable = [self.run_dir / "PRD.md"]

        async def generate(feedback: str | None, round_no: int) -> None:
            await self._agent(
                stage=stage.name, round_no=round_no, system_prompt=system,
                prompt=prompts.prd_prompt(self.config.idea, feedback, list_context(self.run_dir), self._has_brief),
                tools=list(stage.gen_tools), writable=writable, max_turns=self.config.plan_max_turns,
                gate=self._gate(stage, self._prd_check),
            )

        await self._review_loop(stage, paths=writable, generate=generate, check=self._prd_check)

    async def screen_specs(self) -> None:
        """구현 후보를 만들고 조사한 뒤 critic이 거른다. 고르지는 않는다. viable 후보가 없으면 지적을 반영해 다시 만든다."""
        info = self._stage("screen")
        if self._done("screen"):
            return
        stage = STAGES["spec"]
        cand_dir = self.run_dir / "spec-candidates"
        env = prompts.env_note(sorted(self.config.mvp_env))
        system = prompts.SPEC_SYSTEM + env + lessons_prompt(self.lessons_path, stage.name, LEGACY_STAGE[stage.name])
        feedback: str | None = None

        for round_no in range(1, self.config.max_review_rounds + 2):
            if feedback is not None:
                # 다시 만든 후보에 예전 조사 결과가 붙지 않게 지운다
                for d in (cand_dir, self.run_dir / RESEARCH_DIRNAME):
                    shutil.rmtree(d, ignore_errors=True)
            # --resume에서 이미 검사를 통과한 후보가 있으면 다시 만들지 않는다
            if not self._candidates_check()[0]:
                print(f"\n== spec 후보 라운드 {round_no}: 생성", flush=True)
                await self._agent(
                    stage=stage.name, round_no=round_no, system_prompt=system,
                    prompt=prompts.spec_prompt(self.config.idea, self.config.spec_candidates, list_context(self.run_dir),
                                               self._has_brief, feedback),
                    tools=list(stage.gen_tools), writable=[cand_dir], max_turns=self.config.plan_max_turns,
                    gate=self._gate(stage, self._candidates_check),
                )
                ok, report = self._candidates_check()
                if not ok:
                    info.update(status="failed", last_check=report)
                    self._save()
                    raise StageFailed(f"spec 후보가 자동 검사를 통과하지 못했다:\n{report}")
            if self.config.research:
                await self._research(env)
            screening = await self._screen(round_no)
            viable = screening.viable_ids
            # 거르기는 _review_loop를 거치지 않으므로 여기서 지적을 교훈으로 쌓는다
            added = sum(record_lessons(self.lessons_path, stage.name, v.issues) for v in screening.candidates)
            info["rounds"].append({"round": round_no, "viable": viable, "recommended": screening.recommended,
                                   "scores": {v.id: v.score for v in screening.candidates}, "lessons_added": added})
            self._save()
            print(f"  screening: viable {', '.join(viable) or '없음'}"
                  + (f", 추천 {screening.recommended}" if viable else ""), flush=True)
            if viable:
                info.update(status="passed", review=f"reviews/spec-screen-r{round_no}.json")
                self._save()
                return
            feedback = screening.feedback()

        info["status"] = "failed"
        self._save()
        raise StageFailed("실행할 수 있는(viable) spec 후보가 없다. reviews/spec-screen-*.json 참고")

    async def _screen(self, round_no: int) -> Screening:
        order = candidate_ids(self.run_dir / "spec-candidates")
        # 위치 편향을 줄이려고 critic에게 보여 줄 순서를 섞고 기록한다
        random.SystemRandom().shuffle(order)
        self._stage("screen")["order"] = order
        review_rel = f"reviews/spec-screen-r{round_no}.json"
        review_path = self.run_dir / review_rel
        review_path.parent.mkdir(exist_ok=True)
        print(f"\n== spec 후보 라운드 {round_no}: critic 거르기", flush=True)
        await self._agent(
            stage="spec-screen-critic", round_no=round_no, system_prompt=prompts.SCREEN_SYSTEM,
            prompt=prompts.screen_prompt(self.config.idea, STAGES["spec"].rubric, review_rel, order,
                                         self._researched(order), has_context=bool(list_context(self.run_dir)),
                                         has_brief=self._has_brief),
            tools=list(STAGES["spec"].critic_tools), writable=[review_path], max_turns=self.config.critic_max_turns,
            gate=StopGate("spec screening", lambda: check_screening_file(review_path, order), self.config.max_gate_blocks),
        )
        ok, msg = check_screening_file(review_path, order)
        if not ok:
            raise StageFailed(f"spec critic이 유효한 screening을 남기지 못했다: {msg}")
        return load_screening(review_path)

    def _screening(self) -> Screening:
        return load_screening(self.run_dir / self._stage("screen")["review"])

    async def refine_spec(self) -> None:
        """사람이 고른 후보를 spec.json으로 옮기고, 거르기에서 지적이 남았으면 고친다."""
        stage = STAGES["spec"]
        if self._done(stage.name):
            return
        spec_path = self.run_dir / "spec.json"
        chosen = self.state["choice"]["spec"]["id"]
        if not spec_path.exists():
            spec_path.write_text(json.dumps(candidate_spec(self.run_dir / "spec-candidates", chosen), ensure_ascii=False,
                                            indent=2), encoding="utf-8")
        verdict = self._screening().verdict(chosen)
        info = self._stage(stage.name)
        if verdict.clean(self.config.pass_threshold) and self._spec_check()[0]:
            info.update(status="passed", from_screening=True)
            self._save()
            print(f"\n== spec: 후보 {chosen}는 거르기에서 지적 없이 통과해 그대로 쓴다", flush=True)
            return
        env = prompts.env_note(sorted(self.config.mvp_env))
        system = (prompts.SPEC_REVISE_SYSTEM + env
                  + lessons_prompt(self.lessons_path, stage.name, LEGACY_STAGE[stage.name]))

        async def generate(feedback: str | None, round_no: int) -> None:
            # 개정이 중간에 끊겨 spec.json이 깨졌으면 검사 결과를 지적 앞에 붙여 함께 고친다.
            # --resume으로 다시 들어와 고칠 것이 없으면 평가만 다시 받는다
            ok, report = self._spec_check()
            if not ok:
                feedback = report + (f"\n\n{feedback}" if feedback else "")
            elif feedback is None:
                return
            await self._agent(
                stage=stage.name, round_no=round_no, system_prompt=system,
                prompt=prompts.spec_revise_prompt(self.config.idea, chosen, feedback, list_context(self.run_dir),
                                                  self._has_brief),
                tools=list(stage.gen_tools), writable=[spec_path], max_turns=self.config.plan_max_turns,
                gate=self._gate(stage, self._spec_check),
            )

        # 이어 하기가 아니면 거르기에서 이 후보에 남은 지적부터 고친다
        initial = None if info["rounds"] else verdict.feedback()
        await self._review_loop(stage, paths=[spec_path], generate=generate, check=self._spec_check,
                                initial_feedback=initial)

    def _researched(self, ids: list[str] | None) -> list[str]:
        """형식을 갖춘 조사 결과가 있는 후보 id. 조사를 끄고 이어 간 실행에서 없는 파일을 가리키지 않게 한다."""
        return [c for c in ids or [] if not check_research(self.run_dir / RESEARCH_DIRNAME / f"{c}.md")]

    async def _research(self, env: str) -> None:
        """후보마다 조사 세션을 돌려 research/<id>.md를 쓴다. 이미 형식을 갖춘 조사 결과는 다시 만들지 않는다."""
        out_dir = self.run_dir / RESEARCH_DIRNAME
        out_dir.mkdir(exist_ok=True)
        for cid in candidate_ids(self.run_dir / "spec-candidates"):
            path = out_dir / f"{cid}.md"
            if not check_research(path):
                continue

            def check(path: Path = path) -> tuple[bool, str]:
                return self._report(check_research(path), "조사")

            print(f"\n== spec: 후보 {cid} 조사", flush=True)
            await self._agent(
                stage=f"research-{cid}", round_no=1, system_prompt=prompts.RESEARCH_SYSTEM + env,
                prompt=prompts.research_prompt(self.config.idea, cid, list_context(self.run_dir), self._has_brief),
                tools=list(RESEARCH_TOOLS), writable=[path], max_turns=self.config.research_max_turns,
                gate=StopGate("조사", check, self.config.max_gate_blocks),
            )
            ok, report = check()
            if not ok:
                self._stage("spec").update(status="failed", last_check=report)
                self._save()
                raise StageFailed(f"후보 {cid} 조사 결과가 형식 검사를 통과하지 못했다:\n{report}")

    def _wants_design_directions(self) -> bool:
        """사람에게 디자인 방향을 보여 줄 실행인가. 화면이 없는 앱이나 design off, 지정한 DESIGN.md는 아니다."""
        return self.config.design == "auto" and candidates_have_screen(self.run_dir / "spec-candidates")

    async def design_directions(self) -> None:
        """사람이 고르기 전에 디자인 방향 3개를 만든다. 기능은 모든 spec 후보가 같으므로 spec을 고르기 전에 할 수 있다."""
        if not self._wants_design_directions():
            return
        stage = STAGES["design"]
        library = self.config.design_library
        if library is None or not list_library(library):
            raise StageFailed(f"디자인 라이브러리에 DESIGN.md가 없다: {library}")
        # 무작위로 뽑지 않는다. 라이브러리 전체와 목록을 두고 에이전트가 분야에 어울리는 원천을 고른다(concepts.json의 sources)
        picked = self.state.setdefault("design", {"library": str(library), "candidates": list_library(library)})
        self._save()
        concepts = self.run_dir / "concepts.json"
        cand_dir = self.run_dir / "spec-candidates"
        # 기능은 모든 spec 후보가 같다(check_spec_candidates)
        feature_ids = [f["id"] for f in candidate_spec(cand_dir, candidate_ids(cand_dir)[0])["features"]]

        def check() -> tuple[bool, str]:
            problems = check_directions(concepts, picked["candidates"])
            if not problems:
                problems = check_previews(self.run_dir, [str(d["id"]) for d in directions_of(concepts)], feature_ids)
            return self._report(problems, "Design 방향")

        # 방향은 한 번만 만든다. 멈춘 뒤에 --resume하면 이미 있는 방향과 미리보기를 쓴다
        if check()[0]:
            return
        copy_candidates(library, picked["candidates"], self.run_dir)
        write_index(library, picked["candidates"], self.run_dir)
        print(f"\n== design 원천: {library}의 {len(picked['candidates'])}개 중에서 고른다", flush=True)

        print("\n== design: 방향 3개 생성", flush=True)
        await self._agent(
            stage=f"{stage.name}-directions", round_no=1,
            system_prompt=prompts.DIRECTIONS_SYSTEM + lessons_prompt(self.lessons_path, stage.name),
            prompt=prompts.directions_prompt(self.config.idea, feature_ids, list_context(self.run_dir)),
            tools=list(stage.gen_tools), writable=[concepts, self.run_dir / PREVIEWS_DIRNAME],
            max_turns=self.config.design_max_turns,
            gate=StopGate(f"{stage.label} 방향", check, self.config.max_gate_blocks),
        )
        ok, report = check()
        if not ok:
            self._stage(stage.name).update(status="failed", last_check=report)
            self._save()
            raise StageFailed(f"design 방향이 자동 검사를 통과하지 못했다:\n{report}")

    def choose(self) -> None:
        """사람의 선택을 받는다. 고를 것이 남았는데 선택이 없으면 멈춘다.
        구현 후보는 viable이 둘 이상일 때, 디자인 방향은 방향을 만든 실행일 때 고른다."""
        info = self._stage("choice")
        if info["status"] == "done":
            return
        choice = self.state.setdefault("choice", {})
        screening = self._screening()
        viable = screening.viable_ids
        # 잘못된 id로 끝나도 다시 고를 수 있도록 먼저 대기 상태로 둔다
        info["status"] = "awaiting_choice"
        self._save()

        if "spec" not in choice:
            pick = self.config.choose_spec
            if pick == "recommended":
                choice["spec"] = {"id": screening.recommended, "by": "recommended", "reason": self.config.spec_reason}
            elif pick is not None:
                if pick not in viable:
                    raise StageFailed(f"{pick!r}는 고를 수 있는 구현 후보가 아니다. viable: {', '.join(viable)}")
                choice["spec"] = {"id": pick, "by": "human", "reason": self.config.spec_reason}
            elif len(viable) == 1:
                choice["spec"] = {"id": viable[0], "by": "only_viable", "reason": None}
        if "design" not in choice and self._wants_design_directions() and self.config.choose_design is not None:
            try:
                chosen = choose_direction(self.run_dir / "concepts.json", self.config.choose_design, self.config.design_reason)
            except ValueError as e:
                raise StageFailed(str(e)) from e
            choice["design"] = {"id": chosen["id"], "kind": chosen["kind"], "reason": self.config.design_reason}
        self._save()

        missing = [k for k in ("spec", "design") if k not in choice and (k == "spec" or self._wants_design_directions())]
        if missing:
            raise AwaitingChoice(f"사람이 고를 차례다: {', '.join(missing)}")
        info["status"] = "done"
        self._save()
        print(f"\n== 선택: 구현 후보 {choice['spec']['id']} ({choice['spec']['by']})"
              + (f", 디자인 방향 {choice['design']['id']}" if "design" in choice else ""), flush=True)

    async def design(self) -> None:
        """고른 방향으로 DESIGN.md를 쓴다. design off나 화면 없는 앱은 건너뛰고, 지정한 파일은 그대로 쓴다."""
        stage = STAGES["design"]
        if self._done(stage.name, frozenset({"provided", "skipped"})):
            return
        info = self._stage(stage.name)
        mode = self.config.design
        spec = load_spec(self.run_dir / "spec.json")
        if mode == "off" or spec.smoke.url is None:
            # CLI형 앱은 화면이 없으므로 디자인 단계를 건너뛴다
            info["status"] = "skipped"
            self._save()
            print("\n== design: 건너뜀" + ("" if mode == "off" else " (화면이 없는 앱)"), flush=True)
            return
        if mode != "auto":
            shutil.copyfile(Path(mode), self.run_dir / "DESIGN.md")
            # 지정한 파일은 critic도 생성 검사도 거치지 않으므로, 확인할 수 있는 것만 보고 경고로 남긴다
            warnings = check_design_md(self.run_dir / "DESIGN.md", strict=False)
            info.update(status="provided", source=str(mode), warnings=warnings)
            self._save()
            print(f"\n== design: 지정한 DESIGN.md를 쓴다 ({mode})", flush=True)
            for w in warnings:
                print(f"  경고: {w}", flush=True)
            return

        chosen_id = self.state["choice"]["design"]["id"]
        chosen = next(d for d in directions_of(self.run_dir / "concepts.json") if str(d["id"]) == chosen_id)
        # 사람이 미리보기로 이미 골랐으므로 critic 없이 코드 검사(Stop gate)만 거친다
        await self._agent(
            stage=stage.name, round_no=1, system_prompt=prompts.DESIGN_SYSTEM + lessons_prompt(self.lessons_path, stage.name),
            prompt=prompts.design_prompt(self.config.idea, chosen, None, list_context(self.run_dir)),
            tools=list(stage.gen_tools), writable=[self.run_dir / "DESIGN.md"], max_turns=self.config.design_max_turns,
            gate=self._gate(stage, self._design_check),
        )
        ok, report = self._design_check()
        if not ok:
            info.update(status="failed", last_check=report)
            self._save()
            raise StageFailed(f"DESIGN.md가 자동 검사를 통과하지 못했다:\n{report}")
        info["status"] = "passed"
        self._save()

    async def build(self) -> None:
        stage = STAGES["build"]
        if self._done(stage.name):
            return
        spec = load_spec(self.run_dir / "spec.json")
        system = (prompts.BUILD_SYSTEM + prompts.env_note(sorted(self.config.mvp_env))
                  + lessons_prompt(self.lessons_path, stage.name))
        self.app_dir.mkdir(exist_ok=True)

        async def generate(feedback: str | None, round_no: int) -> None:
            await self._agent(
                stage=stage.name, round_no=round_no, system_prompt=system,
                prompt=prompts.build_prompt(spec, feedback, list_context(self.run_dir),
                                            has_design=(self.run_dir / "DESIGN.md").exists(),
                                            has_concepts=(self.run_dir / "concepts.json").exists()),
                tools=list(stage.gen_tools), writable=[self.app_dir], max_turns=self.config.build_max_turns,
                gate=self._gate(stage, self._build_check),
            )

        async def fix(report: str, round_no: int, fix_no: int) -> None:
            await self._agent(
                stage=f"{stage.name}-fix{fix_no}", round_no=round_no, system_prompt=system,
                prompt=prompts.fix_prompt(report),
                tools=list(stage.gen_tools), writable=[self.app_dir], max_turns=self.config.build_max_turns,
                gate=self._gate(stage, self._build_check),
            )

        await self._review_loop(stage, paths=[self.app_dir], generate=generate, check=self._build_check, fix=fix)

    def final_verify(self) -> bool:
        print("\n== 최종 검증 (LLM 없음)", flush=True)
        result = verify_app(self.app_dir, load_spec(self.run_dir / "spec.json"), extra_env=self.config.mvp_env)
        print(result.report())
        self.state["stages"]["verify"] = {
            "status": "passed" if result.ok else "failed",
            "steps": [{"name": s.name, "ok": s.ok, "duration_s": round(s.duration_s, 1)} for s in result.steps],
            "report": result.report(),
        }
        self._save()
        return result.ok

    def write_report(self, error: str | None = None) -> Path:
        spec: Spec | None = None
        if (self.run_dir / "spec.json").exists():
            try:
                spec = load_spec(self.run_dir / "spec.json")
            except Exception:
                spec = None
        stages = self.state["stages"]
        verify_ok = stages.get("verify", {}).get("status") == "passed"
        report = {
            "idea": self.config.idea,
            "brief": BRIEF_NAME if self._has_brief else None,
            "run_dir": self.run_dir.name,
            "renamed_from": self.state.get("renamed_from"),
            "success": verify_ok and error is None,
            # 잘못된 --choose로 끝나도 아직 고를 수 있으므로 대기다
            "status": "awaiting_choice" if self.awaiting_choice else ("success" if verify_ok and error is None else "failed"),
            "error": error,
            "model": self.config.model,
            "stage_models": self.config.stage_models,
            "mvp_env_keys": sorted(self.config.mvp_env),
            "cost_usd": round(self.spent, 4),
            "cost_note": "SDK가 계산한 클라이언트 측 추정치",
            "stages": stages,
            "runs": self.state["runs"],
            "spec": spec.model_dump() if spec else None,
            "design": self.state.get("design"),
            "choice": self.state.get("choice"),
        }
        report_path = self.run_dir / "run_report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        readme = _readme(self.config.idea, spec, stages, self.spent, report["success"], error)
        if report["status"] == "awaiting_choice":
            readme = _choice_readme(self.config.idea, self.run_dir, self.config.out_dir, self.spent, error,
                                    self._screening(), self.state.get("choice", {}), self._wants_design_directions())
        (self.run_dir / "README.md").write_text(readme, encoding="utf-8")
        return report_path

    async def run(self) -> bool:
        error: str | None = None
        try:
            await self.prd()
            await self.screen_specs()
            await self.design_directions()
            self.choose()
            await self.refine_spec()
            # Spec 루프가 최고점 라운드로 되돌린 뒤의 최종 spec.name을 쓴다. --resume에서 spec을 건너뛰어도 여기를 지난다
            self.rename_after_spec()
            await self.design()
            await self.build()
            self.final_verify()
        except AwaitingChoice:
            pass
        except (BudgetExceeded, StageFailed, AgentAborted) as e:
            error = str(e)
            print(f"\n중단: {error}", flush=True)
        report_path = self.write_report(error)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report["status"] == "awaiting_choice":
            print("\n" + (self.run_dir / "README.md").read_text(encoding="utf-8"))
        result = {"success": "성공", "failed": "실패", "awaiting_choice": "선택 대기"}[report["status"]]
        print(f"\n결과: {result}  비용 추정 ${self.spent:.2f}\n폴더: {self.run_dir}\n리포트: {report_path}")
        return report["success"]


def _readme(idea: str, spec: Spec | None, stages: dict[str, Any], cost: float, success: bool, error: str | None) -> str:
    lines = [f"# {spec.name if spec else 'MVP'}", "", f"아이디어: {idea}", ""]
    lines.append(f"결과: {'성공' if success else '실패'} (비용 추정 ${cost:.2f})")
    if error:
        lines += ["", f"중단 사유: {error}"]
    if spec:
        lines += ["", "## 요약", "", spec.summary, "", f"스택: {spec.stack}", "", "## 실행", "", "```bash", "cd app"]
        if spec.install_cmd:
            lines.append(spec.install_cmd)
        # run_cmd가 $PORT를 쓰므로 같은 줄 할당(PORT=8000 cmd)으로는 펼쳐지지 않는다. 먼저 export한다
        lines += ["export PORT=8000", spec.run_cmd, "```", "", "테스트: `" + spec.test_cmd + "`", "", "## 기능", ""]
        lines += [f"- {f.id} {f.title}: {f.description}" for f in spec.features]
    lines += ["", "## 검증 기록", ""]
    for name in STAGES:
        st = stages.get(name)
        if st and not st.get("rounds"):
            # design이 skipped나 provided면 critic 라운드가 없다
            lines.append(f"- {name}: {st['status']}")
        elif st:
            scores = ", ".join(f"r{r['round']} {r['score']}점" for r in st.get("rounds", []))
            lines.append(f"- {name}: {st['status']} ({scores})")
    if "verify" in stages:
        lines.append(f"- 최종 검증: {stages['verify']['status']}")
    lines += ["", "세부 내용은 run_report.json, reviews/, logs/ 참고.", ""]
    return "\n".join(lines)


def _section(text: str, heading: str) -> str:
    """마크다운에서 heading 절의 본문(다음 ## 제목 전까지)."""
    if heading not in text:
        return ""
    return text.split(heading, 1)[1].split("\n## ", 1)[0].strip()


def _choice_readme(
    idea: str, run_dir: Path, out_dir: Path, cost: float, error: str | None,
    screening: Screening, choice: dict[str, Any], wants_design: bool,
) -> str:
    lines = ["# 선택 대기", "", f"아이디어: {idea}", "", f"지금까지 비용 추정 ${cost:.2f}", ""]
    if error:
        lines += [f"직전 선택 오류: {error}", ""]
    lines += ["고르는 방식(사용 흐름)과 디자인 방향을 따로 골라 이어서 실행하라. 모델, effort, 예산은 처음 실행의 값을 이어 쓴다.", ""]
    cmd = [f"uv run mvpgen --out {out_dir} --resume {run_dir.name}"]

    if "spec" in choice:
        lines += [f"## 고르는 방식: {choice['spec']['id']}로 정해짐 ({choice['spec']['by']})", ""]
    else:
        lines += ["## 고르는 방식 (spec-candidates/)", "", f"critic 판단: {screening.summary}", ""]
        for v in screening.candidates:
            cand = candidate(run_dir / "spec-candidates", v.id)
            mark = "추천, " if v.id == screening.recommended else ""
            lines += [f"### {v.id} ({mark}{'viable' if v.viable else '제외'}, {v.score}점)", "",
                      f"- 무엇을 고르나: {cand['decision']}", f"- 이 후보의 방식: {cand['approach']}", f"- critic: {v.summary}"]
            risks = _section((run_dir / RESEARCH_DIRNAME / f"{v.id}.md").read_text(encoding="utf-8"), "## 위험") \
                if (run_dir / RESEARCH_DIRNAME / f"{v.id}.md").exists() else ""
            if risks:
                lines.append(f"- 조사로 본 위험: {risks}")
            lines.append("")
        cmd.append('--choose-spec <id> --spec-reason "고른 이유"')

    if wants_design and "design" not in choice:
        lines += ["## 디자인 방향 (concepts.json, 원천은 design-candidates/)", ""]
        for d in directions_of(run_dir / "concepts.json"):
            lines += [f"### {d['id']} ({d['kind']}) - {', '.join(d['sources'])}", "",
                      f"- 미리보기: {PREVIEWS_DIRNAME}/{d['id']}.html", f"- 은유: {d['metaphor']}",
                      f"- 첫 화면: {d['first_screen']}", f"- 위험: {d['risks']}", ""]
        cmd.append('--choose-design <id> --design-reason "고른 이유"')

    lines += ["```bash", " \\\n  ".join(cmd), "```", ""]
    return "\n".join(lines)
