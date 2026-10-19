"""mvpgen 명령행 진입점."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Annotated

import typer

from mvpgen.identity import DEFAULT_AUDIENCE

# 실패(1), 입력과 인증 오류(2)와 구분한다. 사람이 고르면 이어 갈 수 있는 정상 멈춤이다
EXIT_AWAITING_CHOICE = 3

app = typer.Typer(add_completion=False, help="한 줄 아이디어로 실행 가능한 MVP를 만든다.")


@app.command()
def generate(
    idea: Annotated[str | None, typer.Argument(help="만들 MVP 아이디어 한 줄. --brief만 주면 brief의 첫 줄을 쓴다")] = None,
    brief: Annotated[Path | None, typer.Option(help="인터뷰로 정리한 요구 원문(brief.md). PRD, Spec과 critic이 아이디어 한 줄보다 우선해 읽는다")] = None,
    out: Annotated[Path, typer.Option(help="결과를 저장할 폴더")] = Path("workspace"),
    model: Annotated[str | None, typer.Option(help="사용할 Claude 모델. 기본 claude-opus-5-5, --resume에서 생략하면 처음 값")] = None,
    stage_model: Annotated[list[str] | None, typer.Option(
        help="단계별 모델 STAGE=MODEL, 여러 번 지정 가능. STAGE: prd, spec, design, build, critic(모든 critic), "
             "prd-critic, spec-critic, design-critic, build-critic, research(후보 조사, 기본은 spec 값). "
             "plan과 plan-critic은 prd와 spec 양쪽에 쓴다. "
             "지정하지 않은 단계는 --model. --resume에서는 처음 값 위에 덮어쓴다"
    )] = None,
    effort: Annotated[str | None, typer.Option(help="low, medium, high, xhigh, max. 기본 high, --resume에서 생략하면 처음 값")] = None,
    budget: Annotated[float | None, typer.Option(help="전체 비용 상한(USD, SDK 추정치 기준). 기본 10, --resume에서 생략하면 처음 값")] = None,
    max_review_rounds: Annotated[int, typer.Option(help="단계별 critic 불합격 후 개정 횟수")] = 2,
    max_gate_blocks: Annotated[int, typer.Option(help="세션당 Stop hook이 종료를 막는 최대 횟수")] = 3,
    max_fix_rounds: Annotated[int, typer.Option(help="세션 종료 후에도 검사 실패 시 수정 세션 횟수")] = 2,
    pass_threshold: Annotated[int, typer.Option(help="critic 합격 점수")] = 80,
    resume: Annotated[str | None, typer.Option(help="이어서 실행할 결과 폴더 이름(slug)")] = None,
    secrets: Annotated[Path, typer.Option(help="claude.env, mvp.env가 있는 폴더")] = Path("secrets"),
    lessons: Annotated[Path, typer.Option(help="실행 간 교훈 파일. 저장소에 커밋해 로컬과 Actions가 함께 쓴다")] = Path("lessons.md"),
    context: Annotated[Path | None, typer.Option(help="미리 조사한 참고 자료 폴더. 결과 폴더의 context/로 복사해 PRD, Spec, Build가 읽는다")] = None,
    design: Annotated[str | None, typer.Option(help="auto(기본): 라이브러리 후보로 디자인 방향 3개를 만들고 사람의 선택을 기다린다, off: 끈다, 파일 경로: 그 DESIGN.md를 그대로 쓴다. --resume에서 생략하면 처음 값")] = None,
    design_library: Annotated[Path, typer.Option(help="DESIGN.md 라이브러리 폴더 (<brand>/DESIGN.md)")] = Path("design-library"),
    design_candidates: Annotated[int, typer.Option(help="design auto에서 무작위로 뽑을 후보 수")] = 8,
    design_seed: Annotated[int | None, typer.Option(help="후보 추출 seed. 비우면 무작위이며 state.json에 기록된다")] = None,
    spec_candidates: Annotated[int | None, typer.Option(min=1, max=4, help="Spec 단계가 만들 구현 후보 수. critic이 하나를 고른다. 기본 2, --resume에서 생략하면 처음 값")] = None,
    research: Annotated[bool | None, typer.Option(
        "--research/--no-research", help="Spec 후보마다 웹 검색으로 조사해 research/에 남긴다. 기본 켬, --resume에서 생략하면 처음 값"
    )] = None,
    choose: Annotated[str | None, typer.Option(help="design auto가 방향 3개를 만들고 멈춘 실행에서 고를 방향 id. --resume과 함께 쓴다")] = None,
    reason: Annotated[str | None, typer.Option(help="--choose로 그 방향을 고른 이유. state.json과 concepts.json에 남아 실험 기록이 된다")] = None,
    gha_oidc: Annotated[bool, typer.Option(help="GitHub Actions에서 OIDC 토큰을 자동으로 받아 갱신")] = True,
    oidc_audience: Annotated[str, typer.Option(help="GitHub OIDC 토큰의 audience (federation 규칙과 같아야 함)")] = DEFAULT_AUDIENCE,
) -> None:
    from mvpgen.envfiles import load_claude_env, load_mvp_env
    from mvpgen.identity import GitHubOidcRefresher, anthropic_config_dir, detect_auth
    from mvpgen.pipeline import Pipeline, RunConfig, find_run_dir, make_slug, parse_stage_models, resolve_settings

    try:
        stage_models = parse_stage_models(stage_model or [])
    except ValueError as e:
        raise typer.BadParameter(str(e), param_hint="--stage-model") from e

    if (choose or reason) and not resume:
        raise typer.BadParameter("--choose와 --reason은 방향 선택을 기다리는 실행을 --resume할 때만 쓴다", param_hint="--choose")
    if brief and resume:
        raise typer.BadParameter("--brief는 새 실행에만 쓴다. 이어 하는 실행은 처음 brief.md를 그대로 쓴다", param_hint="--brief")
    if reason and not choose:
        raise typer.BadParameter("--reason은 --choose와 함께 쓴다", param_hint="--reason")

    out = out.resolve()
    secrets = secrets.resolve()
    load_claude_env(secrets)
    mvp_env = load_mvp_env(secrets)
    if resume:
        found = find_run_dir(out, resume)
        if found is None:
            raise typer.BadParameter(f"{out / resume / 'state.json'}가 없다", param_hint="--resume")
        if found.name != resume:
            typer.echo(f"{resume}은 Spec 뒤에 {found.name}으로 이름이 바뀌었다. 그 폴더로 이어서 실행한다")
        run_dir = found
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        idea = idea or state["idea"]
        if choose and state.get("stages", {}).get("design", {}).get("status") != "awaiting_choice":
            raise typer.BadParameter(f"{run_dir.name}은 디자인 방향 선택을 기다리는 실행이 아니다", param_hint="--choose")
    elif not idea and not brief:
        raise typer.BadParameter("아이디어나 --brief를 입력하거나 --resume을 지정하라", param_hint="IDEA")
    else:
        if not idea:
            from mvpgen.context import brief_title

            assert brief is not None
            idea = brief_title(brief.read_text(encoding="utf-8")) if brief.is_file() else ""
            if not idea:
                raise typer.BadParameter(f"{brief}가 없거나 비어 있다", param_hint="--brief")
        run_dir = out / make_slug(idea)
        state = None
    settings = resolve_settings(
        {"model": model, "stage_models": stage_models, "effort": effort, "budget_usd": budget, "design": design,
         "spec_candidates": spec_candidates, "research": research}, state)
    model, stage_models, effort, budget, design = (
        settings["model"], settings["stage_models"], settings["effort"], settings["budget_usd"], settings["design"])
    spec_candidates, research = settings["spec_candidates"], settings["research"]

    refresher = None
    if gha_oidc and GitHubOidcRefresher.available():
        token_file = Path(os.environ.setdefault(
            "ANTHROPIC_IDENTITY_TOKEN_FILE", str(Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "anthropic-oidc.jwt")
        ))
        refresher = GitHubOidcRefresher(token_file, audience=oidc_audience)
        try:
            refresher.start()
        except Exception as e:
            typer.echo(f"GitHub OIDC 토큰을 받지 못했다: {e!r}. 워크플로에 `permissions: id-token: write`가 있는지 확인하라.", err=True)
            raise typer.Exit(2)
        typer.echo(f"GitHub OIDC 토큰을 {refresher.interval:.0f}초마다 갱신한다 (audience {oidc_audience})")

    auth, warnings = detect_auth()
    for w in warnings:
        typer.echo(f"경고: {w}", err=True)
    if auth is None:
        typer.echo(
            "Claude 인증 수단이 없다. 다음 중 하나를 준비하라:\n"
            "  - 구독(Pro, Max) 로그인: 터미널에서 claude를 실행해 /login\n"
            f"  - {secrets / 'claude.env'}에 CLAUDE_CODE_OAUTH_TOKEN (claude setup-token으로 발급, 구독 사용)\n"
            f"  - {secrets / 'claude.env'}에 ANTHROPIC_API_KEY\n"
            "  - Workload Identity Federation 변수 (ANTHROPIC_FEDERATION_RULE_ID, ANTHROPIC_ORGANIZATION_ID,\n"
            "    ANTHROPIC_SERVICE_ACCOUNT_ID, ANTHROPIC_IDENTITY_TOKEN_FILE)\n"
            "  - ~/.config/anthropic의 federation 프로필",
            err=True,
        )
        raise typer.Exit(2)

    protected = [secrets, anthropic_config_dir()]
    if os.environ.get("ANTHROPIC_IDENTITY_TOKEN_FILE"):
        protected.append(Path(os.environ["ANTHROPIC_IDENTITY_TOKEN_FILE"]).expanduser())

    assert idea is not None
    if design not in {"auto", "off"}:
        design_path = Path(design).expanduser().resolve()
        if not design_path.is_file():
            raise typer.BadParameter(f"{design}는 auto, off 또는 DESIGN.md 파일 경로여야 한다", param_hint="--design")
        design = str(design_path)
    elif design == "auto" and not design_library.is_dir():
        raise typer.BadParameter(f"{design_library} 폴더가 없다. scripts/sync_design_library.py로 받거나 --design off", param_hint="--design-library")
    run_dir.mkdir(parents=True, exist_ok=True)
    if brief is not None:
        from mvpgen.context import ContextError, copy_brief

        try:
            copy_brief(brief.expanduser().resolve(), run_dir, list(mvp_env.values()))
        except ContextError as e:
            raise typer.BadParameter(str(e), param_hint="--brief") from e
        typer.echo(f"요구 원문: {brief}")
    if context is not None:
        from mvpgen.context import ContextError, copy_context

        try:
            copied = copy_context(context.expanduser().resolve(), run_dir, list(mvp_env.values()))
        except ContextError as e:
            raise typer.BadParameter(str(e), param_hint="--context") from e
        typer.echo(f"참고 자료: {context} -> {copied}")
    config = RunConfig(
        idea=idea, out_dir=out, model=model, stage_models=stage_models, effort=effort, budget_usd=budget,
        max_review_rounds=max_review_rounds, max_gate_blocks=max_gate_blocks,
        max_fix_rounds=max_fix_rounds, pass_threshold=pass_threshold,
        protected_paths=protected, mvp_env=mvp_env, lessons_path=lessons.resolve(),
        design=design, design_library=design_library.resolve(), design_candidates=design_candidates,
        design_seed=design_seed, choose=choose, choose_reason=reason, spec_candidates=spec_candidates, research=research,
    )
    typer.echo(f"아이디어: {idea}\n폴더: {run_dir}\n모델: {model} (effort {effort}), 예산 ${budget:.2f}")
    if stage_models:
        typer.echo("단계별 모델: " + ", ".join(f"{k}={v}" for k, v in stage_models.items()))
    typer.echo(f"디자인: {design}")
    typer.echo(f"Claude 인증: {auth}")
    typer.echo(f"MVP용 키: {', '.join(sorted(mvp_env)) or '없음'}")
    pipeline = Pipeline(config, run_dir)
    try:
        ok = asyncio.run(pipeline.run())
    finally:
        if refresher:
            refresher.stop()
    if ok:
        raise typer.Exit(0)
    raise typer.Exit(EXIT_AWAITING_CHOICE if pipeline.awaiting_choice else 1)


def main() -> None:
    app()
