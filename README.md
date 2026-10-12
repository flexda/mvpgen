# mvpgen

한 줄 아이디어를 받아 기획, 구현, 검증을 거쳐 실행 가능한 MVP 폴더를 만드는 Claude Agent SDK 파이프라인.

설계 흐름도: https://claude.ai/artifact/WWz5kH2FVB4jys226Ec5Aj

작업 기록: `docs/ARCHIVE.md`

## 준비

```bash
uv sync
```

API 키는 `secrets/` 폴더에 넣는다 (git에서 제외됨, 자세한 내용은 `secrets/README.md`).

- `secrets/claude.env`: `ANTHROPIC_API_KEY=` 뒤에 Claude API 키를 넣는다. 셸에서 `export`한 값이 있으면 그 값이 우선한다.
- `secrets/mvp.env`: 생성될 MVP가 쓸 외부 API 키(날씨, 지도 등)를 넣는다. 값을 넣은 키의 서비스만 에이전트가 쓸 수 있다. 비워 두면 외부 API 없이 만든다.

Claude Code를 따로 설치하지 않아도 된다. Agent SDK에 Claude Code 바이너리가 함께 들어 있다.

### API 키 없이 쓰기 (Workload Identity Federation)

GitHub Actions에서 실행하면 API 키가 필요 없다. 워크플로는 `.github/workflows/mvpgen.yml`에 있다.

1. Console의 Settings > Workload identity에서 GitHub Actions용 issuer, 서비스 계정, federation 규칙을 만든다. 규칙의 match는 이 저장소가 만드는 토큰과 맞아야 한다.
   - issuer: `https://token.actions.githubusercontent.com`
   - audience: `https://api.anthropic.com`
   - subject_prefix 예: `repo:<owner>/<repo>:ref:refs/heads/main` (main에서 수동 실행할 때)
2. 저장소 Settings > Secrets and variables > Actions > Variables에 `ANTHROPIC_FEDERATION_RULE_ID`, `ANTHROPIC_ORGANIZATION_ID`, `ANTHROPIC_SERVICE_ACCOUNT_ID`를 등록한다. 규칙이 여러 워크스페이스에 걸쳐 있으면 `ANTHROPIC_WORKSPACE_ID`도 등록한다. 모두 비밀값이 아니다.
3. MVP가 외부 API 키를 써야 하면 Secret `MVP_ENV`에 `KEY=VALUE` 여러 줄을 넣는다.
4. Actions 탭에서 mvpgen 워크플로를 골라 Run workflow로 아이디어를 입력한다. 결과는 실행 페이지의 artifact로 내려받는다.

동작 방식:

- mvpgen이 GitHub OIDC 토큰을 받아 `ANTHROPIC_IDENTITY_TOKEN_FILE`에 쓰고, 60초마다 새 토큰으로 바꾼다. GitHub 토큰은 약 5분 뒤 만료되고 한 번만 교환할 수 있기 때문이다.
- 토큰 발급 권한(`ACTIONS_ID_TOKEN_REQUEST_*`)은 읽은 직후 환경에서 지운다. 에이전트의 명령과 생성된 앱은 GitHub 토큰을 발급받을 수 없다.
- 페더레이션 변수와 토큰 파일은 생성된 앱의 실행 환경에 넘기지 않는다. 에이전트가 토큰 파일이나 해당 환경변수에 접근하는 명령도 막는다.
- `ANTHROPIC_API_KEY`가 함께 설정되어 있으면 키가 우선한다. mvpgen은 이때 경고를 낸다.

로컬에서 페더레이션을 쓰려면 `secrets/claude.env`의 방법 2를 채우고, IdP가 발급한 JWT를 `ANTHROPIC_IDENTITY_TOKEN_FILE` 경로에 계속 새로 써 줘야 한다. `~/.config/anthropic`의 federation 프로필도 인식한다.

## 빠른 사용법 (GitHub Actions)

```bash
# 1. 실행 (Actions 탭의 Run workflow와 같다)
gh workflow run mvpgen.yml -R flexda/mvpgen -f idea="만들 앱 한 줄 설명" -f budget=3 -f effort=high

# 2. 진행 확인
gh run list -R flexda/mvpgen --workflow mvpgen.yml --limit 3
gh run watch <RUN_ID> -R flexda/mvpgen

# 3. 결과 내려받기 (workspace/는 git에서 제외됨)
gh run download <RUN_ID> -R flexda/mvpgen -D workspace/ci-<RUN_ID>

# 4. 생성된 앱 실행 (경로와 명령은 결과 폴더의 README.md에 있다)
cd workspace/ci-<RUN_ID>/mvpgen-<RUN_ID>/<slug>/app
uv sync
export PORT=8000
uv run uvicorn app.main:app --host 127.0.0.1 --port $PORT   # 스택마다 다름. spec.json의 run_cmd 참고
```

## 로컬 실행

```bash
uv run mvpgen "할 일 목록 웹앱: 추가, 완료 표시, 삭제"
uv run mvpgen "..." --budget 5 --effort medium --max-review-rounds 1
uv run mvpgen --resume 20261012-153000-mvp   # 중단된 실행 이어하기
```

결과는 `workspace/<slug>/`에 생긴다.

```
workspace/
  lessons.md            # critic이 반복해서 지적한 문제. 다음 실행의 프롬프트에 들어간다
  <slug>/
    PRD.md, spec.json   # Plan 단계 산출물
    app/                # 생성된 앱
    reviews/            # 라운드별 critic 평가
    snapshots/          # 라운드별 산출물 (점수가 떨어지면 되돌릴 때 쓴다)
    logs/               # 세션별 대화 기록
    state.json          # 진행 상태 (--resume용)
    run_report.json     # 점수, 비용 추정, gate block 횟수, 최종 검증 결과
    README.md           # 실행 방법 요약
```

## 동작 방식

Python 오케스트레이터가 Plan, Build, 최종 검증, 리포트 순서로 진행한다. 각 단계는 별도의 `query()` 세션이고, 결과는 파일로 넘긴다.

검증 루프는 세 가지다.

1. **Stop hook 게이트 (세션 안):** 에이전트가 끝내려 할 때마다 검사기가 돈다. Plan 단계는 spec 스키마와 PRD 제목을, Build 단계는 install, test, 실행과 smoke를 검사한다. 실패하면 `{"decision": "block"}`으로 종료를 막고 실패 로그를 전달해 같은 세션에서 고치게 한다. 세션당 최대 `--max-gate-blocks`회까지 막는다.
2. **독립 critic (세션 밖):** 검사를 통과하면 맥락을 공유하지 않는 새 세션이 루브릭으로 채점해 `reviews/*.json`을 쓴다. 80점 미만이거나 critical issue가 있으면 지적 사항을 넘겨 다시 만들게 하고, `--max-review-rounds`회까지 반복한다. 점수가 직전 최고점보다 떨어지면 최고점 라운드의 산출물로 되돌린다.
3. **lessons.md (실행 사이):** major 이상의 지적을 누적하고, 다음 실행 때 같은 단계의 시스템 프롬프트에 최근 20개를 넣는다.

### 안전장치

- 단계마다 쓸 수 있는 도구를 `tools`로 제한하고 `permission_mode="dontAsk"`로 실행한다. 목록 밖 도구는 묻지 않고 거부된다.
- PreToolUse hook이 `sudo`, `curl | sh`, `git push`, 작업 폴더 밖 쓰기를 막는다. 쓸 수 있는 위치도 단계마다 다르다. Plan은 `PRD.md`와 `spec.json`, Build는 `app/`, critic은 자기 review 파일에만 쓴다.
- `setting_sources=[]`로 사용자와 프로젝트의 Claude Code 설정을 읽지 않는다.
- `--budget`(기본 $10)을 넘으면 중단한다. 비용은 SDK가 계산한 클라이언트 측 추정치다.

## 테스트

```bash
uv run pytest -q
```

API를 호출하지 않는다. `tests/test_pipeline_flow.py`는 SDK 호출을 가짜 에이전트로 바꿔 Stop gate block, critic 불합격 후 개정, 최종 검증까지 전체 흐름을 돌린다.

## 코드 구성

| 파일 | 역할 |
| --- | --- |
| `cli.py` | 명령행 옵션, 실행 폴더 결정 |
| `pipeline.py` | 단계 순서, 생성자와 critic 루프, 예산, 상태 저장, 리포트 |
| `agents.py` | `query()` 래퍼. 콘솔 출력, 로그, 비용 수집 |
| `gates.py` | Stop hook 게이트 |
| `guards.py` | PreToolUse 명령과 쓰기 경로 가드 |
| `verify.py` | install, test, 실행과 smoke (LLM 없음) |
| `spec.py` | spec.json 스키마, Plan 검사 |
| `critic.py` | review 스키마, 합격 판정, 스냅샷과 롤백 |
| `lessons.py` | 실행 간 교훈 누적 |
| `prompts.py`, `rubrics.py` | 프롬프트와 루브릭 |
