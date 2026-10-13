"""단계 순서, 두 겹의 검증 루프, 상태 저장을 담당하는 오케스트레이터."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from mvpgen import prompts
from mvpgen.agents import AgentRun, run_agent
from mvpgen.critic import RoundTracker, Review, check_review_file, is_accepted, load_review
from mvpgen.gates import StopGate
from mvpgen.lessons import lessons_prompt, record_lessons
from mvpgen.rubrics import BUILD_RUBRIC, PLAN_RUBRIC
from mvpgen.spec import Spec, check_plan, load_spec
from mvpgen.verify import free_port, verify_app

GEN_TOOLS_PLAN = ["Read", "Write", "Edit", "Glob"]
GEN_TOOLS_BUILD = ["Read", "Write", "Edit", "Glob", "Grep", "Bash"]
CRITIC_TOOLS_PLAN = ["Read", "Glob", "Grep", "Write"]
CRITIC_TOOLS_BUILD = ["Read", "Glob", "Grep", "Write", "Bash"]


class BudgetExceeded(RuntimeError):
    pass


class StageFailed(RuntimeError):
    pass


class AgentAborted(RuntimeError):
    """세션이 작업을 시작하지 못하고 끝났다 (API 오류, CLI 실행 실패). 재시도해도 같은 결과가 나온다."""


@dataclass
class RunConfig:
    idea: str
    out_dir: Path
    model: str = "claude-opus-5-5"
    effort: str = "high"
    budget_usd: float = 10.0
    max_review_rounds: int = 2
    max_gate_blocks: int = 3
    max_fix_rounds: int = 2
    pass_threshold: int = 80
    plan_max_turns: int = 30
    build_max_turns: int = 150
    critic_max_turns: int = 60
    protected_paths: list[Path] = field(default_factory=list)
    mvp_env: dict[str, str] = field(default_factory=dict)


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
    """slug 폴더를 찾는다. Plan 뒤에 이름이 바뀌었으면 renamed_from이 slug인 폴더를 돌려준다."""
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
        self.lessons_path = config.out_dir / "lessons.md"
        self._set_run_dir(run_dir)
        self.state: dict[str, Any] = self._load_state()

    def _set_run_dir(self, run_dir: Path) -> None:
        # 모든 단계가 이 세 경로에서 파일 경로를 만든다. 폴더 이름을 바꾸면 여기서 한 번에 갱신한다
        self.run_dir = run_dir
        self.app_dir = run_dir / "app"
        self.state_path = run_dir / "state.json"

    def rename_after_plan(self) -> None:
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
        return {"idea": self.config.idea, "model": self.config.model, "stages": {}, "runs": [], "cost_usd": 0.0}

    def _save(self) -> None:
        self.state_path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _stage(self, name: str) -> dict[str, Any]:
        return self.state["stages"].setdefault(name, {"status": "pending", "rounds": []})

    @property
    def spent(self) -> float:
        return float(self.state["cost_usd"])

    def _remaining(self) -> float:
        left = self.config.budget_usd - self.spent
        if left <= 0.05:
            raise BudgetExceeded(f"예산 ${self.config.budget_usd:.2f}을 모두 썼다 (사용 ${self.spent:.2f})")
        return left

    def _record_run(self, run: AgentRun, round_no: int) -> None:
        self.state["cost_usd"] = self.spent + run.cost_usd
        self.state["runs"].append({**run.to_dict(), "round": round_no})
        self._save()
        status = "완료" if run.ok else f"실패({run.subtype})"
        gate = f", gate block {run.gate['blocks']}회" if run.gate else ""
        print(f"  <- {run.stage} {status}: ${run.cost_usd:.3f}, {run.turns}턴{gate}, 누적 ${self.spent:.2f}", flush=True)

    async def _agent(self, *, stage: str, round_no: int, **kwargs: Any) -> AgentRun:
        run = await run_agent(
            stage=stage,
            cwd=self.run_dir,
            model=self.config.model,
            effort=self.config.effort,
            max_budget_usd=self._remaining(),
            log_path=self.run_dir / "logs" / f"{stage}-r{round_no}.log",
            env=self.config.mvp_env,
            protected=self.config.protected_paths,
            **kwargs,
        )
        self._record_run(run, round_no)
        if run.subtype == "error_max_budget_usd":
            raise BudgetExceeded("세션이 남은 예산을 모두 썼다")
        if run.api_error or run.subtype == "no_result":
            detail = run.result_text or run.error or run.subtype
            raise AgentAborted(f"{stage} 세션이 API 오류로 끝났다: {detail}")
        return run

    # ---- 검사기 ----
    def _plan_check(self) -> tuple[bool, str]:
        problems = check_plan(self.run_dir)
        return (not problems), ("\n".join(f"- {p}" for p in problems) or "Plan 검사 통과")

    def _build_check(self) -> tuple[bool, str]:
        result = verify_app(self.app_dir, load_spec(self.run_dir / "spec.json"), extra_env=self.config.mvp_env)
        return result.ok, result.report()

    # ---- 생성자 + 비평가 루프 ----
    async def _review_loop(
        self,
        *,
        stage: str,
        paths: list[Path],
        generate: Callable[[str | None, int], Any],
        check: Callable[[], tuple[bool, str]],
        fix: Callable[[str, int, int], Any] | None,
        rubric: str,
        critic_tools: list[str],
        critic_port: bool,
    ) -> Review:
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
            critic_gate = StopGate(f"{stage} review", lambda: check_review_file(review_path), self.config.max_gate_blocks)
            port = free_port() if critic_port else None
            await self._agent(
                stage=f"{stage}-critic",
                round_no=round_no,
                system_prompt=prompts.CRITIC_SYSTEM,
                prompt=prompts.critic_prompt(stage, self.config.idea, rubric, review_rel, port),
                tools=critic_tools,
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
    async def plan(self) -> None:
        if self._stage("plan")["status"] in {"passed", "passed_with_issues"}:
            print("plan: 이전 실행 결과를 사용한다")
            return
        system = (prompts.PLAN_SYSTEM + prompts.env_note(sorted(self.config.mvp_env))
                  + lessons_prompt(self.lessons_path, "plan"))
        writable = [self.run_dir / "PRD.md", self.run_dir / "spec.json"]

        async def generate(feedback: str | None, round_no: int) -> None:
            gate = StopGate("Plan", self._plan_check, self.config.max_gate_blocks)
            await self._agent(
                stage="plan", round_no=round_no, system_prompt=system,
                prompt=prompts.plan_prompt(self.config.idea, feedback),
                tools=GEN_TOOLS_PLAN, writable=writable, max_turns=self.config.plan_max_turns, gate=gate,
            )

        await self._review_loop(
            stage="plan", paths=writable, generate=generate, check=self._plan_check, fix=None,
            rubric=PLAN_RUBRIC, critic_tools=CRITIC_TOOLS_PLAN, critic_port=False,
        )

    async def build(self) -> None:
        if self._stage("build")["status"] in {"passed", "passed_with_issues"}:
            print("build: 이전 실행 결과를 사용한다")
            return
        spec = load_spec(self.run_dir / "spec.json")
        system = (prompts.BUILD_SYSTEM + prompts.env_note(sorted(self.config.mvp_env))
                  + lessons_prompt(self.lessons_path, "build"))
        self.app_dir.mkdir(exist_ok=True)

        async def generate(feedback: str | None, round_no: int) -> None:
            gate = StopGate("Build", self._build_check, self.config.max_gate_blocks)
            await self._agent(
                stage="build", round_no=round_no, system_prompt=system,
                prompt=prompts.build_prompt(spec, feedback),
                tools=GEN_TOOLS_BUILD, writable=[self.app_dir], max_turns=self.config.build_max_turns, gate=gate,
            )

        async def fix(report: str, round_no: int, fix_no: int) -> None:
            gate = StopGate("Build", self._build_check, self.config.max_gate_blocks)
            await self._agent(
                stage=f"build-fix{fix_no}", round_no=round_no, system_prompt=system,
                prompt=prompts.fix_prompt(report),
                tools=GEN_TOOLS_BUILD, writable=[self.app_dir], max_turns=self.config.build_max_turns, gate=gate,
            )

        await self._review_loop(
            stage="build", paths=[self.app_dir], generate=generate, check=self._build_check, fix=fix,
            rubric=BUILD_RUBRIC, critic_tools=CRITIC_TOOLS_BUILD, critic_port=True,
        )

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
            "run_dir": self.run_dir.name,
            "renamed_from": self.state.get("renamed_from"),
            "success": verify_ok and error is None,
            "error": error,
            "model": self.config.model,
            "mvp_env_keys": sorted(self.config.mvp_env),
            "cost_usd": round(self.spent, 4),
            "cost_note": "SDK가 계산한 클라이언트 측 추정치",
            "stages": stages,
            "runs": self.state["runs"],
            "spec": spec.model_dump() if spec else None,
        }
        report_path = self.run_dir / "run_report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.run_dir / "README.md").write_text(_readme(self.config.idea, spec, stages, self.spent, report["success"], error),
                                                encoding="utf-8")
        return report_path

    async def run(self) -> bool:
        error: str | None = None
        try:
            await self.plan()
            # Plan 루프가 최고점 라운드로 되돌린 뒤의 최종 spec.name을 쓴다. --resume에서 plan을 건너뛰어도 여기를 지난다
            self.rename_after_plan()
            await self.build()
            self.final_verify()
        except (BudgetExceeded, StageFailed, AgentAborted) as e:
            error = str(e)
            print(f"\n중단: {error}", flush=True)
        report_path = self.write_report(error)
        ok = json.loads(report_path.read_text(encoding="utf-8"))["success"]
        print(f"\n결과: {'성공' if ok else '실패'}  비용 추정 ${self.spent:.2f}\n폴더: {self.run_dir}\n리포트: {report_path}")
        return ok


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
    for name in ("plan", "build"):
        st = stages.get(name)
        if st:
            scores = ", ".join(f"r{r['round']} {r['score']}점" for r in st.get("rounds", []))
            lines.append(f"- {name}: {st['status']} ({scores})")
    if "verify" in stages:
        lines.append(f"- 최종 검증: {stages['verify']['status']}")
    lines += ["", "세부 내용은 run_report.json, reviews/, logs/ 참고.", ""]
    return "\n".join(lines)
