# mvpgen

아이디어(한 줄 또는 인터뷰로 정리한 brief.md)를 받아 기획, 구현 후보 조사, 사람의 선택, 구현, 검증을 거쳐 실행 가능한 MVP 폴더를 만드는 Claude Agent SDK 파이프라인.

설계 흐름도: https://claude.ai/artifact/WWz5kH2FVB4jys226Ec5Aj

작업 기록: `docs/ARCHIVE.md`

## 준비

```bash
uv sync
```

Claude 인증은 다음 중 하나를 쓴다. 위에 있는 것이 우선한다 (Claude Code 인증 우선순위와 같다).

| 방법 | 설정 | 비용 |
| --- | --- | --- |
| API 키 | `secrets/claude.env`에 `ANTHROPIC_API_KEY` | API 크레딧 |
| 구독 토큰 | `secrets/claude.env`에 `CLAUDE_CODE_OAUTH_TOKEN` (`claude setup-token`으로 발급) | 구독 한도 |
| Workload Identity Federation | 아래 절 참고 | API 크레딧 |
| 구독 로그인 | `secrets/claude.env`를 비워 두고 `claude`를 실행해 `/login` | 구독 한도 |

구독 로그인은 mvpgen이 SDK에 들어 있는 Claude Code로 `claude auth status`를 실행해 확인한다. 구독은 사용 한도에 걸리면 단계 중간에 멈출 수 있다. Agent SDK 문서는 제3자 제품이 claude.ai 로그인을 제공하지 말라고 한다. 본인 실험 용도가 여기에 해당하는지는 미확인이다.

API 키 등은 `secrets/` 폴더에 넣는다 (git에서 제외됨, 자세한 내용은 `secrets/README.md`).

- `secrets/claude.env`: 위 표의 인증 정보를 넣는다. 구독 로그인을 쓰면 비워 둔다. 셸에서 `export`한 값이 있으면 그 값이 우선한다.
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
4. 실행과 결과 내려받기는 아래 "빠른 사용법 (GitHub Actions)"을 따른다.

동작 방식:

- mvpgen이 GitHub OIDC 토큰을 받아 `ANTHROPIC_IDENTITY_TOKEN_FILE`에 쓰고, 60초마다 새 토큰으로 바꾼다. GitHub 토큰은 약 5분 뒤 만료되고 한 번만 교환할 수 있기 때문이다.
- 토큰 발급 권한(`ACTIONS_ID_TOKEN_REQUEST_*`)은 읽은 직후 환경에서 지운다. 에이전트의 명령과 생성된 앱은 GitHub 토큰을 발급받을 수 없다.
- 페더레이션 변수와 토큰 파일은 생성된 앱의 실행 환경에 넘기지 않는다. 에이전트가 토큰 파일이나 해당 환경변수에 접근하는 명령도 막는다.
- `ANTHROPIC_API_KEY`가 함께 설정되어 있으면 키가 우선한다. mvpgen은 이때 경고를 낸다.

로컬에서 페더레이션을 쓰려면 `secrets/claude.env`의 방법 2를 채우고, IdP가 발급한 JWT를 `ANTHROPIC_IDENTITY_TOKEN_FILE` 경로에 계속 새로 써 줘야 한다. `~/.config/anthropic`의 federation 프로필도 인식한다.

## 빠른 사용법 (GitHub Actions)

Actions 탭에서 mvpgen 워크플로를 골라 Run workflow로 실행해도 되고, 아래처럼 `gh`로 해도 된다.

```bash
# 1. 실행 (main에서 돌려야 federation 규칙과 맞는다)
gh workflow run mvpgen.yml -R flexda/mvpgen --ref main -f idea="만들 앱 한 줄 설명" -f budget=10 -f effort=high

# 2. 진행 확인
gh run list -R flexda/mvpgen --workflow mvpgen.yml --limit 3
gh run watch <RUN_ID> -R flexda/mvpgen

# 3. 결과 내려받기 (workspace/는 git에서 제외됨)
gh run download <RUN_ID> -R flexda/mvpgen -D workspace/ci-<RUN_ID>

# 4. slug 폴더 확인
ls workspace/ci-<RUN_ID>/mvpgen-<RUN_ID>/
```

- `budget`은 달러 단위 상한이다 (기본 10). 다 쓰면 중간에 멈추고 미완성 앱이 남을 수 있다.
- Actions의 `design` 기본값은 `off`다. 사람이 고르는 지점에서 멈추는 흐름은 한 번에 끝나는 Actions 실행과 맞지 않는다(러너가 사라져 이어 할 수 없다). 그래서 Actions는 `--choose-spec recommended`로 critic 추천을 따라 끝까지 간다. 디자인을 쓰려면 `-f design=<저장소 안 DESIGN.md 경로>`를 준다.
- `<slug>`는 `<시각>-<아이디어의 영문·숫자 단어 최대 4개>` 형식이다. 아이디어가 한글뿐이면 처음에는 `-mvp`로 끝나고, spec이 정해진 뒤 spec의 영문 앱 이름으로 바뀐다 (예: `20261012-064111-mvp` -> `20261012-064111-simple-memo`). 바뀌기 전 이름은 `run_report.json`의 `renamed_from`에 남는다.
- 실행이 일찍 실패하면(예: federation 변수 누락) artifact가 올라가지 않아 `gh run download`가 실패한다. 이때는 `gh run view <RUN_ID> -R flexda/mvpgen --log-failed`로 원인을 본다.
- 생성된 앱의 설치와 실행 명령은 스택마다 다르다. `<slug>/README.md`의 "실행" 절(또는 `spec.json`의 `install_cmd`, `run_cmd`)을 그대로 따른다.
- artifact는 zip이라 실행 권한이 빠진다. 실행 명령이 `./run.sh` 같은 스크립트를 부르면 먼저 `chmod +x`를 한다.

## 로컬 실행

```bash
uv run mvpgen "할 일 목록 웹앱: 추가, 완료 표시, 삭제"
uv run mvpgen --brief brief.md --context contexts/today-exhibitions   # 인터뷰 결과와 참고 자료로 실행
uv run mvpgen "..." --budget 5 --effort medium --max-review-rounds 1
uv run mvpgen --resume 20261012-153000-simple-memo   # 중단된 실행 이어하기
```

`--resume`에는 spec 뒤에 바뀌기 전의 `-mvp` 이름을 줘도 바뀐 폴더를 찾아 이어 간다. 생략한 `--model`, `--stage-model`, `--effort`, `--budget`, `--design`, `--spec-candidates`, `--research`, `--design-refs`는 처음 실행의 값을 이어 쓴다. `--stage-model`은 처음 값 위에 덮어쓴다.

### 흐름

```
[Claude Code] /grilling 인터뷰 -> brief.md (선택)
PRD -> PRD critic
-> spec 후보 2개 (고르는 방식이 서로 다름) -> 후보별 조사 -> spec critic 거르기 (viable, 점수, 추천)
-> 디자인 원천 찾기 -> 디자인 방향 3개와 미리보기
-> 멈춤: 사람이 고르는 방식과 디자인 방향을 고름 (종료 코드 3)
-> 고른 spec 다듬기 -> DESIGN.md -> Build -> Build critic -> 최종 검증
```

### 인터뷰와 brief (`--brief`)

아이디어 한 줄 대신 인터뷰로 정리한 요구를 넘길 수 있다. 이 Claude Code 세션에서 `/grilling`으로 인터뷰한 뒤 결과를 `brief.md`로 저장한다. 제목 구조는 자유지만 다음을 나눠 쓰면 PRD가 안정적으로 읽는다.

```markdown
# <앱 이름 또는 한 줄 요약>
## 대상 사용자
## 꼭 필요한 기능
## 하지 않을 것
## 제약 (데이터, 스택, 기기 등)
```

- brief는 실행 폴더에 `brief.md`로 복사된다. PRD, Spec과 모든 critic이 아이디어 한 줄보다 brief를 먼저 읽는다.
- 아이디어 한 줄을 따로 주지 않으면 brief의 첫 줄이 아이디어가 된다.
- 비어 있거나 200KB를 넘거나 `mvp.env`의 비밀값이 들어 있으면 거부한다. 큰 자료는 `--context`로 넘긴다.
- brief가 없으면 프롬프트는 예전과 같다(아이디어 한 줄이 요구 원문).

### 사람의 선택 (`--choose-spec`, `--choose-design`)

고를 것이 있으면 디자인 방향까지 만든 뒤 멈추고 종료 코드 3으로 끝난다(1은 실패, 2는 입력 오류). 결과 폴더의 README.md에 후보와 이어 할 명령이 나온다.

```bash
uv run mvpgen --out <폴더> --resume <slug> \
  --choose-spec b --spec-reason "동선이 낯설다" \
  --choose-design C --design-reason "잡지 같아서"
```

- 고르는 방식(spec 후보)은 critic이 viable로 판정한 후보가 둘 이상일 때 고른다. 하나뿐이면 그것으로 정한다. 후보마다 결정, 방식, critic 점수, 조사로 본 위험이 README에 나온다.
- 디자인 방향은 design auto이고 화면이 있는 앱일 때 고른다. 방향마다 `previews/<id>.html`을 브라우저로 열어 본다.
- 두 선택의 이유는 따로 받는다. 디자인과 구조를 한 이유로 묶으면 어떤 쪽이 좋았는지 나눌 수 없기 때문이다. 이유는 `state.json`의 `choice`와 `concepts.json`에 남는다.
- 새 실행에서 `--choose-spec recommended`를 주면 critic 추천을 따르고 고르는 방식에서는 멈추지 않는다.
- 없는 id를 주면 대기 상태가 남고 README에 오류가 붙는다. 다시 고르면 된다.

### 단계별 모델 (`--stage-model`)

`--model`은 모든 단계의 기본 모델이다. 단계마다 다른 모델을 쓰려면 `--stage-model STAGE=MODEL`을 여러 번 준다.

| STAGE | 적용되는 세션 |
| --- | --- |
| `prd`, `spec`, `design`, `build` | 그 단계의 생성 세션. `build`는 build-fix, `design`은 원천 찾기와 방향 세션에도 적용된다 |
| `research` | spec 후보 조사 세션. 없으면 `spec` 값 |
| `critic` | 모든 critic |
| `prd-critic`, `spec-critic`, `build-critic` | 그 critic만. `critic`보다 우선한다. `spec-critic`은 거르기에도 적용된다 |
| `plan`, `plan-critic` | 예전 이름. `prd`와 `spec`(critic 포함)에 따로 지정하지 않으면 이 값을 쓴다 |

추천 조합 (2026-10-18, 실험 전 가설). 토큰을 가장 많이 쓰는 Build 생성은 Sonnet으로 내리고, 결과를 판정하는 build-critic과 앞단의 기획, 디자인은 Opus로 둔다. 조사 세션은 턴이 많아 Sonnet으로 둔다.

```bash
uv run mvpgen "..." --model claude-opus-5-5 \
  --stage-model critic=claude-sonnet-5-5 --stage-model build-critic=claude-opus-5-5 \
  --stage-model build=claude-sonnet-5-5 --stage-model research=claude-sonnet-5-5
```

- effort는 모든 단계가 `--effort` 하나를 쓴다.
- 세션마다 실제로 쓴 모델은 `state.json`과 `run_report.json`의 `runs[].model`에 남는다.

### spec 후보와 조사 (`--spec-candidates`, `--research`)

- spec은 후보 `--spec-candidates`개(기본 2, 최대 4)를 `spec-candidates/<id>.json`에 만든다. 후보는 사용자가 겪는 고르는 방식(사용 흐름)에서 서로 다르다. 하나는 무난한 방식, 나머지는 흔하지 않은 방식이다. 기능 id는 모든 후보가 같다.
- 조사 세션이 후보마다 API, 데이터, 라이브러리, 로컬 실행 가능성을 웹으로 확인해 `research/<id>.md`(확인한 것, 위험, 출처)를 쓴다. `--no-research`로 끈다.
- spec critic은 후보를 고르지 않고 거른다. 후보마다 viable 여부, 점수, 지적을 매기고 하나를 추천한다(`reviews/spec-screen-r*.json`). viable 후보가 없으면 지적을 반영해 후보와 조사를 다시 만든다.
- 사람이 고른 후보가 `spec.json`이 된다. 거르기에서 지적이 남았으면 그 지적으로 spec.json만 고친다.

### 참고 자료 넘기기 (`--context`)

미리 조사한 자료(API 문서, 수집해 둔 CSV/JSON, 수집 스크립트)가 있으면 폴더째 넘긴다.

```bash
uv run mvpgen "오늘 뭐하지: 전시 정보를 모아 오늘 볼 만한 전시를 추천" --context contexts/today-exhibitions
```

- 폴더는 결과 폴더의 `context/`로 복사된다. 기획과 조사는 데이터 출처와 실제 필드를 반영하고, 미리보기는 실제 데이터로 채우고, Build는 데이터 파일을 `app/` 안으로 복사해 쓴다. critic도 자료를 함께 본다.
- 수집 스크립트는 참고용이다. 생성된 앱은 실행 중에 크롤링하지 않고 수집해 둔 파일을 쓴다.
- API 키는 자료에 넣지 않는다. 값은 `secrets/mvp.env`(Actions는 Secret `MVP_ENV`)에 두고 자료에는 환경변수 이름만 적는다. 자료에 `mvp.env`의 값이 그대로 있으면 복사하지 않고 멈춘다.
- 숨김 파일은 빼고, 전체 5MB까지 받는다.

### 디자인 (`--design`)

웹앱이면 디자인 방향을 만들고 사람이 고른다. 의외성은 "이 앱의 분야에 어울리는 스타일 가운데 흔하지 않은 표현"이다. 다른 분야의 디자인 언어를 억지로 옮기지 않는다.

```bash
uv run mvpgen "..."                                   # 기본 auto: 원천을 찾아 방향 3개와 미리보기를 만든다
uv run mvpgen "..." --no-design-refs                  # 웹에서 찾지 않고 --design-library만 쓴다
uv run mvpgen "..." --design-library design-refs/exhibition   # 직접 고른 DESIGN.md 폴더를 원천으로 쓴다
uv run mvpgen "..." --design design-library/wired/DESIGN.md   # 고른 DESIGN.md를 그대로 쓴다
uv run mvpgen "..." --design off                      # 디자인을 끈다
```

원천은 다음 순서로 정한다.

1. **레퍼런스 사이트** (`design-sources.toml`): 원천 찾기 세션이 PRD와 brief를 보고 앱이 웹형(콘텐츠를 둘러보는 화면)인지 앱형(도구처럼 쓰는 화면)인지 정한 뒤, 그 유형의 레퍼런스 저장소 안에서만 분야에 어울리는 DESIGN.md를 3~8개 고른다. 웹 도구는 guard가 목록의 도메인으로 묶는다. 고른 URL은 코드가 저장소와 경로를 검사하고 원본을 내려받는다(https, 300KB 이하, 텍스트).
2. **로컬 라이브러리** (`--design-library`, 기본 `design-library/`): 웹 검색이 꺼져 있거나, 고른 것이 검사를 통과하지 못하거나, 2개 넘게 받지 못하면 쓴다. 어떤 원천을 썼는지와 이유는 `state.json`의 `design`에 남는다.

레퍼런스 목록 (2026-10-19 확인, 인증 없이 원본을 받을 수 있고 라이선스가 재사용을 허락하는 곳만 둔다):

| 이름 | 유형 | 저장소 | 라이선스 |
| --- | --- | --- | --- |
| voltagent | web | VoltAgent/awesome-design-md | MIT |
| open-design | web | nexu-io/open-design | Apache-2.0 |
| design-skills | web | bergside/awesome-design-skills | MIT |
| ios-apps | app | meliwat/awesome-ios-design-md | MIT |

- 직접 고른 DESIGN.md를 쓰려면 `<폴더>/<이름>/DESIGN.md` 구조로 모아 `--design-library <폴더>`로 준다. Refero Styles처럼 자동으로 받을 수 없는 사이트의 DESIGN.md는 이 방법으로 쓴다.
- 원천 출처와 라이선스는 `state.json`, 멈춤 README, 생성된 `DESIGN.md`의 `## Sources` 절에 남는다.
- 방향 세션은 `design-candidates/INDEX.md`(이름, 한 줄 설명, 출처)를 보고 원천을 골라 `concepts.json`에 방향 3개(기준안 1, 의외안 2)를 쓰고, 방향마다 `previews/<id>.html`을 만든다. 세 미리보기는 같은 중립 구조(PRD 기능 순서, 실제 데이터) 위에서 디자인만 다르다. 구조는 spec 후보로 따로 고르기 때문이다.
- Stop gate가 코드로 검사한다: 방향마다 본문 대비 4.5:1 이상(hex로 계산), 미리보기마다 외부 리소스 없음, 기능마다 `data-feature` 요소.
- 사람이 고른 방향으로 `DESIGN.md`를 쓴다. 사람이 이미 미리보기로 골랐으므로 디자인 critic은 없고, 프런트매터 색(text, background)의 대비와 형식만 검사한다.
- `--design <파일>`로 지정한 DESIGN.md도 확인할 수 있는 만큼 검사해 경고로 남긴다.
- Build는 DESIGN.md의 토큰과 레이아웃을 따르고, Build critic이 CSS와 360px 폭을 본다.
- 화면이 없는 CLI형 앱(spec 후보의 `smoke.command`)이면 건너뛴다.
- 라이브러리 갱신은 `uv run python scripts/sync_design_library.py`로 한다. 출처 커밋은 `design-library/SOURCE.md`에 있다.

결과는 `workspace/<slug>/`에 생긴다.

```
lessons.md              # 저장소에 커밋된 교훈 파일 (--lessons로 경로 변경)
workspace/
  <slug>/
    brief.md            # 인터뷰 결과 (--brief)
    PRD.md              # 기획
    spec-candidates/    # 구현 후보 (고르는 방식이 다름)
    research/           # 후보별 조사 결과
    spec.json           # 사람이 고른 후보
    design-refs.json    # 원천 찾기 결과 (레퍼런스 URL과 이유)
    design-candidates/  # 디자인 원천과 INDEX.md
    concepts.json       # 디자인 방향 3개, 색 토큰, 사람의 선택
    previews/           # 방향별 미리보기
    DESIGN.md           # Build가 따르는 디자인 시스템
    app/                # 생성된 앱
    reviews/            # critic 평가와 spec 거르기
    snapshots/          # 라운드별 산출물 (점수가 떨어지면 되돌릴 때 쓴다)
    logs/               # 세션별 대화 기록
    state.json          # 진행 상태와 선택 (--resume용)
    run_report.json     # 점수, 비용 추정, 선택, 최종 검증 결과
    README.md           # 실행 방법 요약 (멈춘 동안은 선택 안내)
```

## 동작 방식

Python 오케스트레이터가 위 흐름 순서로 진행한다. 각 단계는 별도의 `query()` 세션이고, 결과는 파일로 넘긴다. 생성자와 critic 루프를 도는 단계(prd, spec, build)는 `pipeline.py`의 단계 표(`STAGES`)에 있다.

검증 장치는 네 가지다.

1. **Stop hook 게이트 (세션 안):** 에이전트가 끝내려 할 때마다 검사기가 돈다. PRD 제목, spec 후보 스키마(기능 id, smoke 종류, approach), 조사 결과 형식, 거르기 결과, 디자인 방향과 미리보기, DESIGN.md, Build의 install, test, 실행과 smoke를 검사한다. 실패하면 `{"decision": "block"}`으로 종료를 막고 실패 내용을 전달해 같은 세션에서 고치게 한다. 세션당 최대 `--max-gate-blocks`회까지 막는다.
2. **독립 critic (세션 밖):** 맥락을 공유하지 않는 새 세션이 루브릭으로 채점한다. PRD critic은 요구 원문을 직접 나눠 Features와 대조한다. spec critic은 후보를 거르기만 하고 고르지 않는다. 80점 미만이거나 critical issue가 있으면 지적을 넘겨 다시 만들게 하고, `--max-review-rounds`회까지 반복한다. 점수가 직전 최고점보다 떨어지면 최고점 라운드의 산출물로 되돌린다.
3. **사람의 선택 (멈춤):** 고르는 방식과 디자인처럼 취향과 의외성이 걸린 판단은 사람이 한다. critic은 실행할 수 없는 후보를 거르는 데까지만 한다.
4. **lessons.md (실행 사이):** major 이상의 지적(거르기 포함)을 저장소 루트의 `lessons.md`에 누적하고, 다음 실행 때 같은 단계의 시스템 프롬프트에 최근 20개를 넣는다. 예전 `[plan]` 교훈은 prd와 spec 양쪽에 들어간다. Actions에서는 실행이 끝나면 `save-lessons` 잡이 새 항목을 최신 main의 `lessons.md`에 합쳐 커밋한다. 그래서 Actions 실행 뒤에는 로컬에서 `git pull`을 먼저 한다.

### 안전장치

- 단계마다 쓸 수 있는 도구를 `tools`로 제한하고 `permission_mode="dontAsk"`로 실행한다. 목록 밖 도구는 묻지 않고 거부된다.
- PreToolUse hook이 `sudo`, `curl | sh`, `git push`, 작업 폴더 밖 쓰기를 막는다. 쓸 수 있는 위치도 세션마다 다르다. PRD는 `PRD.md`, spec은 `spec-candidates/`(고른 뒤에는 `spec.json`), 조사는 자기 `research/<id>.md`, 원천 찾기는 `design-refs.json`, 방향은 `concepts.json`과 `previews/`, Build는 `app/`, critic은 자기 review 파일에만 쓴다.
- 웹 도구(WebSearch, WebFetch)는 조사와 원천 찾기 세션에만 준다. 두 세션에는 셸이 없다. guard가 URL과 검색어에서 `mvp.env` 비밀값을 막고, 원천 찾기 세션은 레퍼런스 도메인 밖으로 나가지 못하게 한다.
- 웹 텍스트는 조사 결과로 들어와 spec critic과 사람의 선택을 거친다. 조사 세션은 spec 파일을 쓸 수 없다.
- `setting_sources=[]`로 사용자와 프로젝트의 Claude Code 설정을 읽지 않는다.
- `--budget`(기본 $10)을 넘으면 중단한다. 비용은 SDK가 계산한 클라이언트 측 추정치다. 웹 검색 요금이 이 추정치에 들어가는지는 미확인이다.

## 테스트

```bash
uv run pytest -q
```

API를 호출하지 않는다. `tests/test_pipeline_flow.py`는 SDK 호출을 가짜 에이전트로 바꿔 Stop gate block, critic 개정, 거르기, 멈춤과 재개, 레퍼런스 원천과 대체 경로, 최종 검증까지 전체 흐름을 돌린다.

## 코드 구성

| 파일 | 역할 |
| --- | --- |
| `cli.py` | 명령행 옵션, 실행 폴더 결정, 이어 할 때 설정 복원 |
| `pipeline.py` | 단계 표와 순서, 생성자와 critic 루프, 거르기, 선택과 멈춤, 예산, 상태 저장, 리포트 |
| `agents.py` | `query()` 래퍼. 콘솔 출력, 로그, 비용 수집 |
| `gates.py` | Stop hook 게이트 |
| `guards.py` | PreToolUse 명령, 쓰기 경로, 웹 범위 가드 |
| `verify.py` | install, test, 실행과 smoke (LLM 없음) |
| `spec.py` | spec 스키마, PRD와 spec 후보 검사 |
| `critic.py` | review와 거르기 스키마, 합격 판정, 스냅샷과 롤백 |
| `research.py` | 조사 결과 형식 검사 |
| `refsources.py` | 레퍼런스 사이트 목록, URL 검사, 원본 내려받기 |
| `design.py` | 원천 목록(INDEX), 방향, 미리보기, 대비, DESIGN.md 검사 |
| `context.py` | 참고 자료와 brief 복사, 비밀값 검사 |
| `lessons.py` | 실행 간 교훈 누적 |
| `prompts.py`, `rubrics.py` | 프롬프트와 루브릭 |
