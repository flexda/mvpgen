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
from mvpgen.critic import RoundTracker, Review, check_review_file, is_accepted, load_review
from mvpgen.design import (check_design, check_directions, choose_direction, copy_candidates, directions_of, list_library,
                           pick_candidates)
from mvpgen.gates import StopGate
from mvpgen.lessons import lessons_prompt, record_lessons
from mvpgen.rubrics import BUILD_RUBRIC, DESIGN_RUBRIC, PRD_RUBRIC, SPEC_RUBRIC
from mvpgen.spec import Spec, candidate_ids, candidate_spec, check_prd, check_spec, check_spec_candidates, load_spec
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


# 실행 순서대로 둔다. 이 순서가 --stage-model 키와 README 검증 기록의 순서가 된다
STAGES: dict[str, Stage] = {s.name: s for s in (
    Stage("prd", "PRD", ("Read", "Write", "Edit", "Glob"), ("Read", "Glob", "Grep", "Write"), PRD_RUBRIC),
    Stage("spec", "Spec", ("Read", "Write", "Edit", "Glob"), ("Read", "Glob", "Grep", "Write"), SPEC_RUBRIC),
    Stage("design", "Design", ("Read", "Write", "Edit", "Glob", "Grep"), ("Read", "Glob", "Grep", "Write"), DESIGN_RUBRIC),
    Stage("build", "Build", ("Read", "Write", "Edit", "Glob", "Grep", "Bash"), ("Read", "Glob", "Grep", "Write", "Bash"),
          BUILD_RUBRIC, critic_port=True),
)}

# 이 상태로 끝난 단계는 --resume에서 다시 돌리지 않는다
DONE_STATUSES = frozenset({"passed", "passed_with_issues"})


class BudgetExceeded(RuntimeError):
    pass


class StageFailed(RuntimeError):
    pass


class AwaitingChoice(RuntimeError):
    """사람이 고를 차례라 실행을 멈춘다. 실패가 아니다. --resume --choose로 이어 간다."""


# 단계가 prd와 spec으로 나뉘기 전 이름. --stage-model과 lessons.md의 plan 값을 두 단계가 이어 쓴다
LEGACY_STAGE = {"prd": "plan", "spec": "plan"}

# --stage-model에 쓸 수 있는 키. critic은 모든 critic에 적용되고, 개별 critic 키가 그보다 우선한다
STAGE_MODEL_KEYS = (*STAGES, "plan", "critic", *(f"{s}-critic" for s in STAGES), "plan-critic")


def model_for(stage: str, stage_models: dict[str, str], default: str) -> str:
    """세션 이름(prd, build-fix1, spec-critic 등)에 쓸 모델. build-fixN, design-directions는 앞 단계 설정을 따른다.
    prd와 spec은 따로 지정하지 않으면 plan 값을 쓴다."""
    if stage.endswith("-critic"):
        legacy = LEGACY_STAGE.get(stage.removesuffix("-critic"))
        return (stage_models.get(stage) or (legacy and stage_models.get(f"{legacy}-critic"))
                or stage_models.get("critic") or default)
    base = stage.split("-", 1)[0]
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
    design_candidates: int = 8
    design_seed: int | None = None
    # design auto에서 사람이 고른 방향 id와 이유. 방향을 만든 뒤 멈춘 실행을 --resume으로 이어 갈 때 준다
    choose: str | None = None
    choose_reason: str | None = None


# 실행 설정 중 --resume에서 플래그를 생략하면 처음 실행의 값을 이어 쓰는 것과 그 기본값
SETTING_DEFAULTS: dict[str, Any] = {
    "model": "claude-opus-5-5", "stage_models": {}, "effort": "high", "budget_usd": 10.0, "design": "auto",
    "spec_candidates": 2,
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
                                  "spec_candidates": config.spec_candidates}

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
        return self.state["stages"].get("design", {}).get("status") == "awaiting_choice"

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

    def _spec_check(self) -> tuple[bool, str]:
        # 후보를 고르기 전에는 후보들을, 고른 뒤에는 spec.json을 검사한다
        if (self.run_dir / "spec.json").exists():
            return self._report(check_spec(self.run_dir), "Spec")
        return self._report(check_spec_candidates(self.run_dir / "spec-candidates", self.config.spec_candidates), "Spec 후보")

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
        winners: Callable[[], list[str] | None] | None = None,
        on_review: Callable[[Review], None] | None = None,
    ) -> Review:
        """winners가 후보 id 목록을 돌려주는 라운드에서는 critic이 그중 하나를 review의 winner로 고른다.
        on_review는 라운드 스냅샷을 찍기 전에 불린다(고른 후보를 산출물로 옮길 때 쓴다)."""
        stage = spec.name
        info = self._stage(stage)
        tracker = RoundTracker(paths, self.run_dir, self.run_dir / "snapshots" / stage)
        feedback: str | None = None
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
            choices = winners() if winners else None
            critic_gate = StopGate(f"{stage} review", lambda: check_review_file(review_path, choices),
                                   self.config.max_gate_blocks)
            port = free_port() if spec.critic_port else None
            await self._agent(
                stage=f"{stage}-critic",
                round_no=round_no,
                system_prompt=prompts.CRITIC_SYSTEM,
                prompt=prompts.critic_prompt(stage, self.config.idea, spec.rubric, review_rel, port,
                                          has_context=bool(list_context(self.run_dir)),
                                          has_design=(self.run_dir / "DESIGN.md").exists(), has_brief=self._has_brief,
                                          candidates=choices),
                tools=list(spec.critic_tools),
                writable=[review_path],
                max_turns=self.config.critic_max_turns,
                gate=critic_gate,
            )
            ok_file, msg = check_review_file(review_path, choices)
            if not ok_file:
                raise StageFailed(f"{stage} critic이 유효한 review를 남기지 못했다: {msg}")
            review = load_review(review_path)
            if on_review:
                on_review(review)
            accepted = is_accepted(review, self.config.pass_threshold)
            rolled_back = tracker.record(round_no, review)
            added = record_lessons(self.lessons_path, stage, review.issues)
            info["rounds"].append({
                "round": round_no, "score": review.score, "pass": review.passed, "accepted": accepted,
                "critical": review.critical_count, "issues": len(review.issues), "rolled_back": rolled_back,
                "lessons_added": added, **({"winner": review.winner} if choices else {}),
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

    async def spec(self) -> None:
        """1라운드는 후보를 만들고 critic이 하나를 골라 spec.json으로 옮긴다. 2라운드부터는 spec.json만 고친다."""
        stage = STAGES["spec"]
        if self._done(stage.name):
            return
        cand_dir = self.run_dir / "spec-candidates"
        spec_path = self.run_dir / "spec.json"
        lessons = lessons_prompt(self.lessons_path, stage.name, LEGACY_STAGE[stage.name])
        env = prompts.env_note(sorted(self.config.mvp_env))
        info = self.state.setdefault("spec", {})

        async def generate(feedback: str | None, round_no: int) -> None:
            if not spec_path.exists():
                await self._agent(
                    stage=stage.name, round_no=round_no, system_prompt=prompts.SPEC_SYSTEM + env + lessons,
                    prompt=prompts.spec_prompt(self.config.idea, self.config.spec_candidates, list_context(self.run_dir),
                                               self._has_brief),
                    tools=list(stage.gen_tools), writable=[cand_dir], max_turns=self.config.plan_max_turns,
                    gate=self._gate(stage, self._spec_check),
                )
                return
            if feedback is None:
                # --resume으로 고른 뒤에 다시 들어왔다. spec.json이 검사를 통과하면 평가만 다시 받고,
                # 개정이 중간에 끊겨 깨졌으면 검사 결과를 지적으로 삼아 고친다
                ok, report = self._spec_check()
                if ok:
                    return
                feedback = report
            await self._agent(
                stage=stage.name, round_no=round_no, system_prompt=prompts.SPEC_REVISE_SYSTEM + env + lessons,
                prompt=prompts.spec_revise_prompt(self.config.idea, info["winner"], feedback,
                                                  list_context(self.run_dir), self._has_brief),
                tools=list(stage.gen_tools), writable=[spec_path], max_turns=self.config.plan_max_turns,
                gate=self._gate(stage, self._spec_check),
            )

        def winners() -> list[str] | None:
            if spec_path.exists():
                return None
            # 위치 편향을 줄이려고 critic에게 보여 줄 순서를 섞고 기록한다
            order = candidate_ids(cand_dir)
            random.SystemRandom().shuffle(order)
            info["order"] = order
            return order

        def on_review(review: Review) -> None:
            if review.winner is None or spec_path.exists():
                return
            spec_path.write_text(json.dumps(candidate_spec(cand_dir, review.winner), ensure_ascii=False, indent=2),
                                 encoding="utf-8")
            info["winner"] = review.winner
            self._save()
            print(f"  spec: 후보 {review.winner}를 spec.json으로 골랐다", flush=True)

        await self._review_loop(stage, paths=[cand_dir, spec_path], generate=generate, check=self._spec_check,
                                winners=winners, on_review=on_review)

    async def design(self) -> None:
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
            info["status"] = "provided"
            info["source"] = str(mode)
            self._save()
            print(f"\n== design: 지정한 DESIGN.md를 쓴다 ({mode})", flush=True)
            return

        library = self.config.design_library
        if library is None or not list_library(library):
            raise StageFailed(f"디자인 라이브러리에 DESIGN.md가 없다: {library}")
        picked = self.state.get("design")
        if picked is None:
            # --resume에서도 같은 후보를 쓰도록 seed와 후보를 state에 남긴다
            seed = self.config.design_seed if self.config.design_seed is not None else random.SystemRandom().randrange(2**31)
            picked = {"seed": seed, "candidates": pick_candidates(library, self.config.design_candidates, seed)}
            self.state["design"] = picked
            self._save()
        copy_candidates(library, picked["candidates"], self.run_dir)
        print(f"\n== design 후보 (seed {picked['seed']}): {', '.join(picked['candidates'])}", flush=True)

        concepts = self.run_dir / "concepts.json"
        # 방향은 한 번만 만든다. 멈춘 뒤나 고른 뒤에 --resume하면 이미 있는 방향을 쓴다
        if info["status"] != "awaiting_choice" and picked.get("choice") is None:
            await self._directions(stage, picked["candidates"])
        if picked.get("choice") is None:
            if self.config.choose is None:
                info["status"] = "awaiting_choice"
                self._save()
                raise AwaitingChoice("디자인 방향을 사람이 고를 차례다")
            try:
                chosen = choose_direction(concepts, self.config.choose, self.config.choose_reason)
            except ValueError as e:
                raise StageFailed(str(e)) from e
            picked["choice"] = {"id": self.config.choose, "kind": chosen["kind"], "reason": self.config.choose_reason}
            info["status"] = "chosen"
            self._save()
            print(f"\n== design: 사람이 고른 방향 {chosen['id']} ({chosen['kind']})", flush=True)
        chosen = next(d for d in directions_of(concepts) if str(d["id"]) == picked["choice"]["id"])

        system = prompts.DESIGN_SYSTEM + lessons_prompt(self.lessons_path, stage.name)
        writable = [self.run_dir / "DESIGN.md"]

        async def generate(feedback: str | None, round_no: int) -> None:
            await self._agent(
                stage=stage.name, round_no=round_no, system_prompt=system,
                prompt=prompts.design_prompt(self.config.idea, chosen, feedback, list_context(self.run_dir)),
                tools=list(stage.gen_tools), writable=writable, max_turns=self.config.design_max_turns,
                gate=self._gate(stage, self._design_check),
            )

        await self._review_loop(stage, paths=writable, generate=generate, check=self._design_check)

    async def _directions(self, stage: Stage, candidates: list[str]) -> None:
        """디자인 방향 3개를 concepts.json에 쓴다. 고르는 것은 사람이다."""
        concepts = self.run_dir / "concepts.json"

        def check() -> tuple[bool, str]:
            problems = check_directions(concepts, candidates)
            return (not problems), ("\n".join(f"- {p}" for p in problems) or "Design 방향 검사 통과")

        print("\n== design: 방향 3개 생성", flush=True)
        await self._agent(
            stage=f"{stage.name}-directions", round_no=1,
            system_prompt=prompts.DIRECTIONS_SYSTEM + lessons_prompt(self.lessons_path, stage.name),
            prompt=prompts.directions_prompt(self.config.idea, candidates, list_context(self.run_dir)),
            tools=list(stage.gen_tools), writable=[concepts], max_turns=self.config.design_max_turns,
            gate=StopGate(f"{stage.label} 방향", check, self.config.max_gate_blocks),
        )
        ok, report = check()
        if not ok:
            self._stage(stage.name).update(status="failed", last_check=report)
            self._save()
            raise StageFailed(f"design 방향이 자동 검사를 통과하지 못했다:\n{report}")

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
            "spec_choice": self.state.get("spec"),
        }
        report_path = self.run_dir / "run_report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        readme = _readme(self.config.idea, spec, stages, self.spent, report["success"], error)
        if report["status"] == "awaiting_choice":
            readme = _choice_readme(self.config.idea, self.run_dir, self.config.out_dir, self.spent, error)
        (self.run_dir / "README.md").write_text(readme, encoding="utf-8")
        return report_path

    async def run(self) -> bool:
        error: str | None = None
        try:
            await self.prd()
            await self.spec()
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


def _choice_readme(idea: str, run_dir: Path, out_dir: Path, cost: float, error: str | None) -> str:
    lines = ["# 디자인 방향 선택 대기", "", f"아이디어: {idea}", "", f"지금까지 비용 추정 ${cost:.2f}", ""]
    if error:
        lines += [f"직전 선택 오류: {error}", ""]
    lines += ["방향 3개 중 하나를 골라 이어서 실행하라. 모델, effort, 예산은 처음 실행의 값을 이어 쓴다.",
              "자세한 내용은 concepts.json과 design-candidates/ 참고.", ""]
    for d in directions_of(run_dir / "concepts.json"):
        lines += [f"## {d['id']} ({d['kind']}) - {', '.join(d['sources'])}", "", f"- 은유: {d['metaphor']}",
                  f"- 첫 화면: {d['first_screen']}", f"- 위험: {d['risks']}", ""]
    lines += ["```bash", f'uv run mvpgen --out {out_dir} --resume {run_dir.name} --choose <id> --reason "고른 이유"', "```", ""]
    return "\n".join(lines)
