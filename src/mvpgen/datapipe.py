"""데이터 파이프라인 모드: API 자료를 받아 Supabase 적재 파이프라인을 만든다.

단계는 data-plan(PIPELINE.md, pipeline.json)과 data-build(app/), 최종 검증이다.
상태 저장, 예산, Stop gate, critic 루프는 앱 모드의 Pipeline을 그대로 쓴다.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mvpgen import data_prompts
from mvpgen.context import list_context
from mvpgen.dataspec import DataSpec, check_data_plan, load_data_spec
from mvpgen.gates import StopGate
from mvpgen.lessons import lessons_prompt
from mvpgen.pipeline import (
    CRITIC_TOOLS_BUILD,
    CRITIC_TOOLS_PLAN,
    GEN_TOOLS_BUILD,
    GEN_TOOLS_PLAN,
    AgentAborted,
    BudgetExceeded,
    Pipeline,
    RunConfig,
    StageFailed,
)
from mvpgen.prompts import env_note
from mvpgen.verify import VerifyResult

# 지문 계산에서 뺄 폴더 (설치와 테스트가 만드는 파일)
FINGERPRINT_SKIP = {".venv", "__pycache__", ".pytest_cache", "node_modules", ".ruff_cache"}

# (app_dir, spec, run_dir, label, page_cap) -> VerifyResult. 실제로는 DbVerifier.verify
Verifier = Callable[[Path, DataSpec, Path, str, "int | None"], VerifyResult]


class DataPipeline(Pipeline):
    def __init__(self, config: RunConfig, run_dir: Path, verifier: Verifier,
                 check_pages: int = 2, final_pages: int | None = None) -> None:
        super().__init__(config, run_dir)
        self.verifier = verifier
        # 검사마다 적재를 두 번 하므로 API 호출을 줄이려고 페이지 수를 제한한다. 최종 검증만 final_pages(None이면 전체)로 돈다
        self.check_pages = check_pages
        self.final_pages = final_pages
        self.state.setdefault("mode", "data")
        # 마지막으로 통과한 검사의 app/ 지문과 보고. Stop gate 통과 직후 루프가 같은 검사(API 수집 2회)를 반복하지 않게 한다
        self._passed: tuple[str, str] | None = None

    @property
    def spec_path(self) -> Path:
        return self.run_dir / "pipeline.json"

    # ---- 검사기 ----
    def _plan_check(self) -> tuple[bool, str]:
        problems = check_data_plan(self.run_dir, sorted(self.config.mvp_env))
        return (not problems), ("\n".join(f"- {p}" for p in problems) or "Plan 검사 통과")

    def _db_check(self, label: str, page_cap: int | None) -> VerifyResult:
        result = self.verifier(self.app_dir, load_data_spec(self.spec_path), self.run_dir, label, page_cap)
        self.state["last_evidence"] = f"db/{label}.md"
        self._save()
        return result

    def _fingerprint(self) -> str:
        h = hashlib.sha256()
        for p in sorted(self.app_dir.rglob("*")):
            rel = p.relative_to(self.app_dir)
            if p.is_file() and not FINGERPRINT_SKIP & set(rel.parts):
                h.update(f"{rel}\0{p.stat().st_size}\0{p.stat().st_mtime_ns}\n".encode())
        return h.hexdigest()

    def _build_check(self) -> tuple[bool, str]:
        fp = self._fingerprint()
        if self._passed and self._passed[0] == fp:
            return True, self._passed[1]
        self.state["db_checks"] = self.state.get("db_checks", 0) + 1
        label = f"check-{self.state['db_checks']}"
        result = self._db_check(label, self.check_pages)
        report = result.report() + f"\n\n자세한 결과: db/{label}.md"
        # install이 uv.lock 같은 파일을 만들 수 있으므로 검사가 끝난 뒤의 지문을 저장한다
        self._passed = (self._fingerprint(), report) if result.ok else None
        return result.ok, report

    def _critic_prompt(self, stage: str, rubric: str, review_rel: str, port: int | None) -> str:
        return data_prompts.critic_prompt(stage, self.config.idea, rubric, review_rel,
                                          has_context=bool(list_context(self.run_dir)),
                                          evidence=self.state.get("last_evidence"))

    # ---- 단계 ----
    async def plan(self) -> None:
        if self._stage("data-plan")["status"] in {"passed", "passed_with_issues"}:
            print("data-plan: 이전 실행 결과를 사용한다")
            return
        system = (data_prompts.DATA_PLAN_SYSTEM + env_note(sorted(self.config.mvp_env))
                  + lessons_prompt(self.lessons_path, "data-plan"))
        writable = [self.run_dir / "PIPELINE.md", self.spec_path]

        async def generate(feedback: str | None, round_no: int) -> None:
            gate = StopGate("Data plan", self._plan_check, self.config.max_gate_blocks)
            await self._agent(
                stage="data-plan", round_no=round_no, system_prompt=system,
                prompt=data_prompts.plan_prompt(self.config.idea, feedback, list_context(self.run_dir)),
                tools=GEN_TOOLS_PLAN, writable=writable, max_turns=self.config.plan_max_turns, gate=gate,
            )

        await self._review_loop(
            stage="data-plan", paths=writable, generate=generate, check=self._plan_check, fix=None,
            rubric=data_prompts.DATA_PLAN_RUBRIC, critic_tools=CRITIC_TOOLS_PLAN, critic_port=False,
        )

    async def build(self) -> None:
        if self._stage("data-build")["status"] in {"passed", "passed_with_issues"}:
            print("data-build: 이전 실행 결과를 사용한다")
            return
        spec = load_data_spec(self.spec_path)
        system = (data_prompts.DATA_BUILD_SYSTEM + env_note(sorted(self.config.mvp_env))
                  + lessons_prompt(self.lessons_path, "data-build"))
        self.app_dir.mkdir(exist_ok=True)

        async def generate(feedback: str | None, round_no: int) -> None:
            gate = StopGate("Data build", self._build_check, self.config.max_gate_blocks)
            await self._agent(
                stage="data-build", round_no=round_no, system_prompt=system,
                prompt=data_prompts.build_prompt(spec, feedback, list_context(self.run_dir),
                                                 self.state.get("last_evidence")),
                tools=GEN_TOOLS_BUILD, writable=[self.app_dir], max_turns=self.config.build_max_turns, gate=gate,
            )

        async def fix(report: str, round_no: int, fix_no: int) -> None:
            gate = StopGate("Data build", self._build_check, self.config.max_gate_blocks)
            await self._agent(
                stage=f"data-build-fix{fix_no}", round_no=round_no, system_prompt=system,
                prompt=data_prompts.fix_prompt(report),
                tools=GEN_TOOLS_BUILD, writable=[self.app_dir], max_turns=self.config.build_max_turns, gate=gate,
            )

        # 이미 DB에 적용한 마이그레이션을 파일만 되돌리면 DB 기록과 어긋나므로 점수가 떨어져도 되돌리지 않는다
        await self._review_loop(
            stage="data-build", paths=[self.app_dir], generate=generate, check=self._build_check, fix=fix,
            rubric=data_prompts.DATA_BUILD_RUBRIC, critic_tools=CRITIC_TOOLS_BUILD, critic_port=False, rollback=False,
        )

    def final_verify(self) -> bool:
        print(f"\n== 최종 검증 (LLM 없음, 수집 페이지 {self.final_pages or '전체'})", flush=True)
        result = self._db_check("final", self.final_pages)
        print(result.report())
        self.state["stages"]["verify"] = {
            "status": "passed" if result.ok else "failed",
            "steps": [{"name": s.name, "ok": s.ok, "duration_s": round(s.duration_s, 1)} for s in result.steps],
            "report": result.report(),
            "evidence": "db/final.md",
        }
        self._save()
        return result.ok

    def write_report(self, error: str | None = None) -> Path:
        spec: DataSpec | None = None
        if self.spec_path.exists():
            try:
                spec = load_data_spec(self.spec_path)
            except Exception:
                spec = None
        stages = self.state["stages"]
        success = stages.get("verify", {}).get("status") == "passed" and error is None
        report: dict[str, Any] = {
            "mode": "data",
            "goal": self.config.idea,
            "run_dir": self.run_dir.name,
            "success": success,
            "error": error,
            "model": self.config.model,
            "stage_models": self.config.stage_models,
            "mvp_env_keys": sorted(self.config.mvp_env),
            "check_pages": self.check_pages,
            "final_pages": self.final_pages,
            "db_checks": self.state.get("db_checks", 0),
            "cost_usd": round(self.spent, 4),
            "cost_note": "SDK가 계산한 클라이언트 측 추정치",
            "stages": stages,
            "runs": self.state["runs"],
            "pipeline": spec.model_dump() if spec else None,
        }
        report_path = self.run_dir / "run_report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.run_dir / "README.md").write_text(_readme(self.config.idea, spec, stages, self.spent, success, error),
                                                encoding="utf-8")
        return report_path

    async def run(self) -> bool:
        error: str | None = None
        try:
            await self.plan()
            await self.build()
            self.final_verify()
        except (BudgetExceeded, StageFailed, AgentAborted) as e:
            error = str(e)
            print(f"\n중단: {error}", flush=True)
        report_path = self.write_report(error)
        ok = json.loads(report_path.read_text(encoding="utf-8"))["success"]
        print(f"\n결과: {'성공' if ok else '실패'}  비용 추정 ${self.spent:.2f}\n폴더: {self.run_dir}\n리포트: {report_path}")
        return ok


def _readme(goal: str, spec: DataSpec | None, stages: dict[str, Any], cost: float, success: bool, error: str | None) -> str:
    lines = [f"# {spec.name if spec else '데이터 파이프라인'}", "", f"목표: {goal}", ""]
    lines.append(f"결과: {'성공' if success else '실패'} (비용 추정 ${cost:.2f})")
    if error:
        lines += ["", f"중단 사유: {error}"]
    if spec:
        lines += ["", "## 요약", "", spec.summary, "", f"원천: {spec.source.name} ({spec.source.endpoint})",
                  "", "## 실행", "", "```bash", "cd app"]
        if spec.install_cmd:
            lines.append(spec.install_cmd)
        lines += [
            "export DATABASE_URL='<Supabase Session pooler 접속 문자열>'",
            *([f"export {spec.source.key_env}='<API 키>'"] if spec.source.key_env else []),
            'supabase db push --db-url "$DATABASE_URL" --workdir .',
            spec.ingest_cmd, "```", "", "테스트: `" + spec.test_cmd + "`", "", "## 테이블", "",
        ]
        lines += [f"- {t.name}: {t.description}" for t in spec.tables]
    lines += ["", "## 검증 기록", ""]
    for name in ("data-plan", "data-build"):
        st = stages.get(name)
        if st:
            scores = ", ".join(f"r{r['round']} {r['score']}점" for r in st.get("rounds", []))
            lines.append(f"- {name}: {st['status']} ({scores})")
    if "verify" in stages:
        lines.append(f"- 최종 검증: {stages['verify']['status']} (근거 db/final.md)")
    lines += ["", "세부 내용은 run_report.json, reviews/, db/, logs/ 참고.", ""]
    return "\n".join(lines)
