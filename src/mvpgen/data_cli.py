"""mvpdata 명령행 진입점: API 자료를 받아 Supabase 적재 파이프라인을 만든다.

mvpgen과 같은 Typer 앱에 두 번째 명령을 더하면 `mvpgen "아이디어"` 형식이 깨지므로 별도 진입점으로 둔다.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(add_completion=False, help="API 자료를 받아 Supabase 적재 파이프라인을 만든다.")


@app.command()
def generate(
    goal: Annotated[str | None, typer.Argument(help="파이프라인 목표 한 줄 (예: MMCA 전시 정보를 매일 적재)")] = None,
    context: Annotated[Path | None, typer.Option(help="API 문서와 샘플이 있는 폴더. 결과 폴더의 context/로 복사한다")] = None,
    out: Annotated[Path, typer.Option(help="결과를 저장할 폴더")] = Path("workspace"),
    model: Annotated[str, typer.Option(help="사용할 Claude 모델")] = "claude-opus-5-5",
    stage_model: Annotated[list[str] | None, typer.Option(
        help="단계별 모델 STAGE=MODEL. STAGE: data-plan, data-build, critic, data-plan-critic, data-build-critic"
    )] = None,
    effort: Annotated[str, typer.Option(help="low, medium, high, xhigh, max")] = "high",
    budget: Annotated[float, typer.Option(help="전체 비용 상한(USD, SDK 추정치 기준)")] = 10.0,
    max_review_rounds: Annotated[int, typer.Option(help="단계별 critic 불합격 후 개정 횟수")] = 2,
    max_gate_blocks: Annotated[int, typer.Option(help="세션당 Stop hook이 종료를 막는 최대 횟수")] = 3,
    max_fix_rounds: Annotated[int, typer.Option(help="세션 종료 후에도 검사 실패 시 수정 세션 횟수")] = 2,
    pass_threshold: Annotated[int, typer.Option(help="critic 합격 점수")] = 80,
    check_pages: Annotated[int, typer.Option(help="중간 검사의 수집 페이지 수 (검사마다 적재를 두 번 한다)")] = 2,
    final_pages: Annotated[int, typer.Option(help="최종 검증의 수집 페이지 수. 0이면 전체")] = 0,
    resume: Annotated[str | None, typer.Option(help="이어서 실행할 결과 폴더 이름(slug)")] = None,
    secrets: Annotated[Path, typer.Option(help="claude.env, mvp.env, supabase.env가 있는 폴더")] = Path("secrets"),
    lessons: Annotated[Path, typer.Option(help="실행 간 교훈 파일")] = Path("lessons.md"),
    supabase_bin: Annotated[str, typer.Option(help="Supabase CLI 실행 파일")] = "supabase",
) -> None:
    from mvpgen.datapipe import DataPipeline
    from mvpgen.dbverify import DbVerifier, url_secrets
    from mvpgen.envfiles import SUPABASE_FILE, SUPABASE_URL_KEY, load_claude_env, load_mvp_env, load_supabase_url
    from mvpgen.identity import anthropic_config_dir, detect_auth
    from mvpgen.pipeline import RunConfig, make_slug, parse_stage_models

    try:
        stage_models = parse_stage_models(stage_model or [])
    except ValueError as e:
        raise typer.BadParameter(str(e), param_hint="--stage-model") from e

    out = out.resolve()
    secrets = secrets.resolve()
    load_claude_env(secrets)
    mvp_env = load_mvp_env(secrets)
    db_url = load_supabase_url(secrets)
    # 에이전트 세션은 이 프로세스의 환경을 물려받는다. 셸에서 export한 접속 문자열이 넘어가지 않게 지운다
    os.environ.pop(SUPABASE_URL_KEY, None)
    # 데이터 모드는 에이전트에게 API 키를 주지 않는다. 셸에 export한 같은 이름의 키도 지운다 (샘플과 적재에는 mvp_env로 넘긴다)
    for key in mvp_env:
        os.environ.pop(key, None)
    if not db_url:
        typer.echo(f"{secrets / SUPABASE_FILE}에 {SUPABASE_URL_KEY}가 없다. Supabase 대시보드의 Connect > Session pooler 문자열을 넣어라",
                   err=True)
        raise typer.Exit(2)
    bin_path = shutil.which(supabase_bin)
    if bin_path is None:
        typer.echo(f"Supabase CLI({supabase_bin})를 찾지 못했다. --supabase-bin으로 경로를 지정하라", err=True)
        raise typer.Exit(2)

    if resume:
        run_dir = out / resume
        if not (run_dir / "state.json").exists():
            raise typer.BadParameter(f"{run_dir / 'state.json'}가 없다", param_hint="--resume")
        goal = goal or json.loads((run_dir / "state.json").read_text(encoding="utf-8"))["idea"]
    elif not goal:
        raise typer.BadParameter("목표를 입력하거나 --resume을 지정하라", param_hint="GOAL")
    elif context is None:
        raise typer.BadParameter("API 자료 폴더를 지정하라", param_hint="--context")
    else:
        run_dir = out / ("data-" + make_slug(goal))

    auth, warnings = detect_auth()
    for w in warnings:
        typer.echo(f"경고: {w}", err=True)
    if auth is None:
        typer.echo("Claude 인증 수단이 없다. 구독 로그인(claude 실행 후 /login)이나 secrets/claude.env를 준비하라 (README 참고)",
                   err=True)
        raise typer.Exit(2)

    secret_values = list(mvp_env.values()) + url_secrets(db_url)
    run_dir.mkdir(parents=True, exist_ok=True)
    if context is not None and not resume:
        from mvpgen.context import ContextError, copy_context

        try:
            copied = copy_context(context.expanduser().resolve(), run_dir, secret_values)
        except ContextError as e:
            raise typer.BadParameter(str(e), param_hint="--context") from e
        typer.echo(f"참고 자료: {context} -> {copied}")

    assert goal is not None
    config = RunConfig(
        idea=goal, out_dir=out, model=model, stage_models=stage_models, effort=effort, budget_usd=budget,
        max_review_rounds=max_review_rounds, max_gate_blocks=max_gate_blocks,
        max_fix_rounds=max_fix_rounds, pass_threshold=pass_threshold,
        protected_paths=[secrets, anthropic_config_dir()], mvp_env=mvp_env, lessons_path=lessons.resolve(),
        extra_secrets=url_secrets(db_url),
    )
    verifier = DbVerifier(db_url=db_url, supabase_bin=bin_path, extra_env=mvp_env)
    typer.echo(f"목표: {goal}\n폴더: {run_dir}\n모델: {model} (effort {effort}), 예산 ${budget:.2f}")
    if stage_models:
        typer.echo("단계별 모델: " + ", ".join(f"{k}={v}" for k, v in stage_models.items()))
    typer.echo(f"Claude 인증: {auth}")
    typer.echo(f"API 키: {', '.join(sorted(mvp_env)) or '없음'}")
    typer.echo(f"수집 페이지: 중간 검사 {check_pages}, 최종 {final_pages or '전체'}")
    problems = verifier.preflight(run_dir)
    if problems:
        typer.echo("DB 사전 점검 실패 (Claude는 아직 부르지 않았다):\n" + "\n".join(f"  - {p}" for p in problems), err=True)
        raise typer.Exit(2)
    typer.echo("DB 사전 점검 통과")
    pipe = DataPipeline(config, run_dir, verifier.verify, check_pages=check_pages, final_pages=final_pages or None)
    ok = asyncio.run(pipe.run())
    raise typer.Exit(0 if ok else 1)


def main() -> None:
    app()
