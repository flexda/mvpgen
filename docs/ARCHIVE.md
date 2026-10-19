# mvpgen 구축 기록

2026-10-12, Claude Code(Opus 5.5) 세션 한 번으로 진행한 작업의 기록.

## 목표

한 줄 아이디어를 넣으면 기획, 구현, 검증을 거쳐 실행 가능한 MVP 폴더를 만드는 시스템.

## 결정 사항

| 항목 | 결정 | 근거 |
| --- | --- | --- |
| Input / Output | 아이디어 한 줄 -> 동작하는 코드 | 사용자 선택 |
| 구현 방식 | Claude Agent SDK (Python, uv) | 사용자 선택, 전역 규칙(uv 사용) |
| 대상 스택 | 아이디어에 따라 Plan 에이전트가 선택 | 사용자 선택 |
| 오케스트레이션 | Python 코드가 단계 순서와 검증을 결정 | LLM 하나에 전체를 맡기지 않기 위해 |
| 자체 검증 루프 | Stop hook 게이트 + 독립 critic + lessons.md | 사용자 질문("스스로 검증하고 개선하는 루프가 반영됐나")에 따라 추가 |
| 인증 | Workload Identity Federation (GitHub Actions) | 사용자 요청, API 키 불필요 |
| 저장소 | github.com/flexda/mvpgen (private) | 사용자 요청 |
| 기본 모델 | `claude-opus-5-5`, effort `high` | |
| 디자인 단계 (2026-10-18) | Plan과 Build 사이에 Design 단계 추가. 원천은 기존 DESIGN.md 라이브러리 | 사용자 선택. 1차 구축 뒤 "기능 추가 안 함" 원칙의 예외 |
| 디자인 방향 (2026-10-18) | 분야에 맞는 무난한 화면보다 의외성을 우선 | 사용자 요청("뻔한 전시추천사이트처럼 보여야 할까") |
| 의외성 강제 방식 (2026-10-18) | 후보 추출은 코드가 무작위로(seed 기록), 기준안 선택은 gate가 차단 | LLM에게 고르게만 하면 매번 비슷한 선택으로 수렴하기 때문 |
| Actions 인증 비용 (2026-10-18) | WIF와 API 크레딧을 유지하고 크레딧을 충전 | 사용자 선택. Pro 구독 토큰(`CLAUDE_CODE_OAUTH_TOKEN`)으로 바꾸는 안을 검토했다 |
| 인증 선택지 안내 (2026-10-18) | 인증, 실행 위치, 비용 설계 전에 구독과 API 방식 선택지를 비용과 함께 먼저 안내한다 | 10-12 설계 때 API 키만 안내돼 구독 사용 가능성을 몰랐다(아래 "인증 설계에서 빠진 안내") |
| 실행 결과 보관 (2026-10-18) | Actions artifact를 `workspace/ci-<run>/`에 내려받고 스크린샷을 함께 둔다 | 기존 실행과 같은 위치. artifact는 14일 뒤 지워진다 |
| 구독 인증 인정 (2026-10-18) | `detect_auth()`가 `/login` 구독 로그인과 `CLAUDE_CODE_OAUTH_TOKEN`을 인정한다. 우선순위는 Claude Code 인증 문서를 따른다 | 로컬에서 API 크레딧 없이 실험하기 위해. PR #4 |
| 단계별 모델 (2026-10-18) | `--stage-model STAGE=MODEL`로 plan, design, build, critic별 모델을 정한다. 기본값은 바꾸지 않는다 | 사용자 요청. 기본값을 바꾸면 전부 Opus인 기준선과 비교할 수 없다. PR #5 |
| 데이터 파이프라인 모드 (2026-10-19) | API 자료를 받아 Supabase 적재 파이프라인을 만드는 독립 모드 `mvpdata`. 기존 Plan/Design/Build 흐름은 그대로 둔다 | 사용자 선택. 목적은 mvpgen이 외부 DB 적재까지 할 수 있는지 보는 것. 브랜치 `exp/supabase-pipeline` |
| 적재 대상 (2026-10-19) | 클라우드 Supabase 실험 전용 새 프로젝트 | 사용자 선택. 프로젝트 생성과 접속 문자열 입력은 사용자가 한다 |
| API 정보 입력 (2026-10-19) | 기존 `--context` 폴더 재사용, 키는 `mvp.env` | 사용자 선택. 비밀값 검사 로직을 그대로 쓴다 |
| 마이그레이션 방식 (2026-10-19) | Supabase 정식 규칙: 적용한 파일은 잠그고 변경은 새 파일로 추가. 적용은 `supabase db push --db-url` | 사용자 선택(A안). 검사마다 스키마를 지우고 다시 만드는 B안은 정식 흐름과 달라 버림 |

## 구조

```
아이디어 -> Plan 생성 <-> Stop hook(spec 검사) -> Plan critic --불합격--> 개정(최대 2회)
                                                     | 합격
         Build 생성 <-> Stop hook(install/test/smoke) -> Build critic --불합격--> 개정(최대 2회)
                                                     | 합격
         최종 검증(LLM 없음) -> Report(README, run_report.json)
```

| 루프 | 위치 | 동작 |
| --- | --- | --- |
| Stop hook 게이트 | 세션 안 | 종료하려 할 때 검사기 실행, 실패하면 `decision: block`으로 같은 세션에서 수정. 세션당 최대 3회 |
| 독립 critic | 세션 밖 | 맥락을 공유하지 않는 새 세션이 루브릭으로 채점. 80점 미만 또는 critical이면 개정. 점수가 떨어지면 최고점 라운드로 롤백 |
| lessons.md | 실행 사이 | major 이상 지적을 누적해 다음 실행 프롬프트에 주입(최근 20개) |

설계 흐름도: https://claude.ai/artifact/WWz5kH2FVB4jys226Ec5Aj

## 진행 순서

| 순서 | 작업 | 결과 |
| --- | --- | --- |
| 1 | 요구사항 확인, 계획 수립 | Agent SDK 공식 문서로 API 확인 |
| 2 | 사용자 피드백으로 루프 설계 보강 | Stop hook(공식 문서로 Python 지원과 block 형식 확인) + critic 추가, 흐름도 아티팩트 게시 |
| 3 | 구현 | `src/mvpgen/` 12개 모듈, 오프라인 테스트 |
| 4 | `secrets/` 폴더 | `claude.env`(Claude 인증), `mvp.env`(MVP용 외부 API 키). git 제외, 권한 600 |
| 5 | Workload Identity Federation 지원 | 인증 수단 판별, GitHub OIDC 토큰 60초 갱신, 토큰 발급 권한을 환경에서 제거 |
| 6 | GitHub 저장소 생성, 푸시 | private, `main` 브랜치 |
| 7 | Console federation 규칙 설정 | 규칙 조건을 실제 토큰 형식에 맞게 두 차례 수정 |
| 8 | 1차 실행 | 인증 통과로 보임, 크레딧 부족(`Credit balance is too low`)으로 중단, 비용 $0 |
| 9 | 2차 실행(크레딧 충전 후) | 성공, 약 3분, 추정 $0.44 |

## Federation 설정 (비밀값 아님)

| 항목 | 값 |
| --- | --- |
| Issuer | `fdis_01F4TeUwGRkHaDgdbpEeDm7d` (github-actions) |
| 규칙 | `fdrl_01EBcCvCzwe7tToErypmQVHE` (mvpgen-main) |
| 서비스 계정 | `svac_019bvMb7g5jNcQiZYGiWNf1E` (mvpgen-ci) |
| 조직 | `77b1477b-ff54-4971-91d9-5b7801c8c010` |
| 워크스페이스 | Default (하나뿐이라 `ANTHROPIC_WORKSPACE_ID` 불필요) |
| 제목 접두사 | `repo:flexda@68023258/mvpgen@1415097267:ref:refs/heads/main` |
| 필수 클레임 | `ref=refs/heads/main`, `event_name=workflow_dispatch`, `repository=flexda/mvpgen`, `repository_owner=flexda`, `repository_owner_id=68023258` |
| 범위 / 토큰 수명 | `workspace:developer` / 3,600초 |

저장소 Variables에 규칙, 서비스 계정, 조직 ID를 등록했다.

## 2차 실행 결과

[실행 로그](https://github.com/flexda/mvpgen/actions/runs/38213721713)

| Step | Result | Cost |
| --- | --- | --- |
| Auth | Workload Identity Federation | |
| Plan | PRD + spec, 5 features | $0.08 |
| Plan critic | 88, pass, 4 minor | $0.08 |
| Build | FastAPI + SQLite, 7 tests pass | $0.11 |
| Build critic | 87, pass, AC1-AC7 checked live with curl | $0.16 |
| Final verify | install / test / run+smoke pass | |

생성물: `simple-memo` 메모 웹앱. 로컬 사본은 `workspace/ci-38213721713/`(git 제외).

## 발견하고 고친 문제

| 문제 | 발견 경위 | 조치 |
| --- | --- | --- |
| 규칙 제목 접두사를 옛 형식(`repo:owner/repo:...`)으로 안내 | GitHub OIDC 문서 확인 중. 2026-07-15 이후 저장소는 owner와 저장소 숫자 ID가 들어간 형식이다 | GitHub API(`actions/oidc/customization/sub`)로 실제 형식을 조회해 정정 |
| 워크플로가 시작되지 않음 | 1차 실행 시 HTTP 422 | job 수준 `env`에서 `runner.temp`를 뺐다. 기본값은 mvpgen이 `$RUNNER_TEMP`로 처리 |
| API 오류가 "자동 검사 실패"로 잘못 보고됨 | 1차 실행 로그 | API 오류면 즉시 중단하고 API 메시지를 그대로 표시 |
| 실행 안내 `PORT=8000 cmd --port $PORT`가 동작하지 않음 | 2차 실행의 Build critic 지적 | `export PORT=8000`을 먼저 쓰도록 README 생성기와 Build 프롬프트 수정 |

## 검증 현황

| 항목 | 상태 |
| --- | --- |
| 오프라인 테스트 59개 | 통과 |
| 번들 Claude Code가 federation 변수를 인증 수단으로 선택 | 확인 (`claude auth status`: `Profile: env-quad`) |
| 실제 federation 인증 | 확인 (2차 실행 성공) |
| 전체 파이프라인 E2E | 확인 (2차 실행) |
| critic 불합격 후 개정, Stop hook block | 실제 실행에서는 미발생. 오프라인 테스트로만 확인 |
| 10분 이상 실행 시 토큰 갱신 | 미확인. 3분 만에 끝나 토큰 수명을 넘지 않았다 |

## 남은 일

- 더 큰 아이디어로 10분 이상 실행해 토큰 갱신을 확인한다.
- critic 불합격, Stop hook block이 실제로 일어나는 사례로 루프 동작을 확인한다.
- 생성물에 실행 중 만든 파일(`memos.db`)이 섞인다. artifact 제외 목록이나 정리 단계를 검토한다.
- 알려진 한계: 에이전트가 `echo $KEY`로 MVP용 키를 출력하면 `logs/`에 남을 수 있다.

## 2026-10-13: 1차 구축 마무리

이 날로 1차 구축을 마친다. 이후에는 기능을 더하지 않고 이 시스템의 문제점을 점검한다.

전체 실험 보고서(설계, 데이터 흐름, 루프, 문제와 원인, 무지의 영역, 다음 시스템 제안): `docs/report-2026-10-13/index.html`

### 추가한 기능

| 커밋 | 내용 |
| --- | --- |
| `7f1a5bd` | Plan 의도 검증: spec.json `intent`(아이디어 요구마다 담당 feature), Stop gate 검사, Plan 루브릭 6번 "의도 대응". 한글 아이디어의 `<시각>-mvp` 폴더를 Plan 뒤에 `<시각>-<spec.name>`으로 변경, `--resume`이 옛 이름도 찾음. README 빠른 사용법 리뷰 지적 8건 반영 |
| `df0367c` | `--context`: 참고 자료 폴더를 `<run>/context/`로 복사(숨김 파일 제외, 5MB, `mvp.env` 값이 있으면 중단). Plan, Build, critic 프롬프트에 안내 |
| `e2c241e` | 참고 자료 `contexts/today-exhibitions` (원문에 있던 서비스키는 환경변수 이름으로 교체) |
| `6ca8790` | `lessons.md`를 저장소 루트로 옮기고, Actions의 `save-lessons` 잡이 새 항목을 main에 합쳐 커밋 |

### 실행 결과

| run | 아이디어 | 코드 | 결과 | Plan / Build | 비용 | 시간 |
| --- | --- | --- | --- | --- | --- | --- |
| [38339954369](https://github.com/flexda/mvpgen/actions/runs/38339954369) | 읽은 책 기록장 (low, $2) | `5094fa7` 의도 검증 전 | 성공, 폴더 `-mvp` | 90 / 90 | $0.55 | 2.7분 |
| [38339966010](https://github.com/flexda/mvpgen/actions/runs/38339966010) | 읽은 책 기록장 (low, $2) | `7f1a5bd` 의도 검증 후 | 성공, 폴더 `book-log`, intent 3개 | 88 / 90 | $0.45 | 5.3분 |
| [38343685543](https://github.com/flexda/mvpgen/actions/runs/38343685543) | 오늘 뭐하지 (high, $5, context) | `e2c241e` | 성공, 폴더 `today-exhibition-picks` | 88 / 92 | $1.96 | 8.6분 |

- 의도 검증 전후 비교: 새 코드에서는 아이디어에 없는 기능(다 읽음 표시, 삭제)이 빠졌고, Plan critic이 요구마다 담당 feature와 AC를 대조했다. 점수와 비용 차이는 1회씩이라 판단하지 않는다.
- 오늘 뭐하지: 수집 CSV의 실제 컬럼과 MMCA API 문서의 필드를 그대로 기획에 반영했고, 실행 중 크롤링은 하지 않았다.

### 이번에 드러난 문제 (점검 대상)

| 문제 | 근거 |
| --- | --- |
| 생성된 앱이 휴대폰 폭(420px)에서 가로로 넘친다. critic과 최종 검증이 화면 폭을 보지 않는다 | 오늘 뭐하지 스크린샷 |
| 모든 실행이 critic 1라운드 통과, gate block 0회. 개정 루프와 Stop hook block은 여전히 실제로 일어나지 않았다 | 세 실행의 run_report |
| 같은 minor 지적이 실행마다 반복된다(smoke 문자열이 명세에 없음, 의존성 누락, 접속 URL 없음). lessons는 major 이상만 기록해 쌓이지 않는다 | 책 기록장 두 실행의 review |
| 생성된 앱의 외부 API 경로(MMCA 새로고침)를 실제 키로 확인하지 않았다 | 키 없이 로컬 실행 |
| 생성된 앱은 git 제외 폴더(`workspace/`)에 있어, 계속 다듬을 앱의 버전 관리 방법이 없다 | 오늘 뭐하지 후속 작업 논의 |
| 키가 들어 있던 자료를 넘기는 과정에서, 다른 도구의 작업 로그에 서비스키 값이 출력됐다 | 키 정리 작업 로그. 재발급 검토 |

### 검증 현황 갱신

| 항목 | 상태 |
| --- | --- |
| 오프라인 테스트 | 73개 통과 |
| 의도 검증, 폴더 이름 변경, `--context` | 실제 Actions 실행으로 확인 |
| 옛 이름으로 `--resume`, 자료 안의 비밀값 차단 | 단위 테스트로만 확인 |
| `save-lessons` 잡 (artifact 다운로드, 병합, 커밋) | 미확인. push만 했고 실행은 하지 않았다. 다음 실행에서 확인 |
| 10분 이상 실행 시 토큰 갱신 | 미확인. 가장 긴 실행이 8.6분 |

## 2026-10-18: Design 단계 추가

1차 구축 이후 처음 더한 기능이다. 전시 추천 사이트를 만들기 전에, 사용자가 "뻔한 전시 추천 사이트처럼 보일 필요는 없다. 의외성을 맡을 창의적 에이전트를 넣자"고 정했다.

| 항목 | 내용 |
| --- | --- |
| 흐름 | Plan -> Design -> Build -> 최종 검증. 화면이 없는 CLI형 앱은 건너뜀 |
| 원천 | `design-library/`: VoltAgent/awesome-design-md(MIT)의 DESIGN.md 84개를 저장소에 복사. 실행 중 네트워크 없음 |
| 의외성 장치 | 코드가 후보 8개를 무작위로 뽑음(seed 기록). 에이전트는 그 안에서 기준안 1개와 의외안 2개를 내고, gate가 기준안 선택을 막음 |
| 산출물 | `concepts.json`(방향 3개, 선택 이유), `DESIGN.md`(앱에 맞게 옮긴 디자인 시스템) |
| 평가 | Design critic 루브릭 5개 항목(의외성, 맥락 번역, 사용성, 구현 가능성, 기능 대응). Build 루브릭 6번에 DESIGN.md 준수 추가 |
| 옵션 | `--design auto|off|<파일>`, `--design-seed`, `--design-candidates`, `--design-library`. Actions 입력 `design`, `design_seed` |
| 검증 | 오프라인 테스트 85개 통과. 실제 실행은 아직 하지 않음 |

### 결정 과정

| 순서 | 질문이나 제안 | 결정 | 버린 안과 이유 |
| --- | --- | --- | --- |
| 1 | mvpgen에 디자인 레퍼런스 조사 에이전트가 있나 | 없음을 코드로 확인(웹 도구, 디자인 프롬프트, 디자인 루브릭 모두 없음). 사용자가 "Design 단계 추가"를 선택 | context 폴더에 수동으로 넣기(현재 프롬프트가 context를 데이터 출처로만 읽게 해서 반영 여부가 불확실), 그대로 실행(기준선만 얻음) |
| 2 | WebSearch와 WebFetch로 레퍼런스를 조사해 DESIGN.md를 만드는 에이전트(첫 계획) | 사용자가 거절하고 "이미 DESIGN.md를 제공하는 사이트를 쓰자"고 함 | 웹 조사 에이전트: 사용자 거절. Actions 환경에서 WebSearch가 동작하는지도 미확인이었음 |
| 3 | 원천 조사 | VoltAgent/awesome-design-md 채택(MIT, 84개, Google Stitch 형식, 파일당 24~35KB). 미술관 브랜드는 없음 | getdesign.md는 같은 파일의 미리보기 사이트, webdesignhot은 출처 확인이 덜 됨 |
| 4 | 브랜드 하나 고르기(Runway, Airbnb, WIRED, Oura)와 넣는 방식 질문 | 답하지 않고 방향을 바꿈: "꼭 뻔한 전시 추천 사이트처럼 보여야 할까? 의외성을 맡을 창의적 에이전트를 넣자" | 브랜드를 직접 지정하는 방식은 `--design <파일>` 옵션으로만 남김 |
| 5 | 의외성을 어떻게 보장할까 | 코드가 후보 8개를 무작위로 뽑고, 에이전트는 기준안 1개와 의외안 2개를 낸 뒤 의외안만 고를 수 있음. 라이브러리는 저장소에 복사해 실행 중 네트워크를 쓰지 않음 | LLM 자유 선택(같은 "의외의" 선택으로 수렴), 실행 중 다운로드(재현성과 네트워크 의존) |
| 6 | 작업 보관 | 브랜치 `feat/design-stage`에 커밋, push, draft PR #1. 관련 없는 미커밋 변경(`docs/mmca-pipeline-report` 브랜치)은 제외 | main 직접 반영(실행 전 확인 절차를 건너뜀) |
| 7 | 결정 기록 위치 | 이 ARCHIVE에 계속 적재 | 별도 DECISIONS.md(역할은 분리되지만 사용자가 문서 하나로 관리하기를 택함) |

한계: 루브릭의 대비(WCAG)와 360px 항목은 critic이 문서와 CSS를 읽고 판단하는 것이지 측정이 아니다. Design critic에는 Bash가 없고 Build critic에는 브라우저가 없다. 위 "휴대폰 폭" 문제는 이 변경으로 닫히지 않았고, 실제 확인은 playwright 360px 스크린샷으로 한다.

미확인: critic의 의외성 판정이 안정적인지, Design 단계로 늘어나는 비용이 얼마인지. 첫 실행 뒤 run_report.json으로 확인한다.

## 2026-10-18: Design 단계 첫 실행 (오늘 뭐하지)

PR #1을 main에 병합(`69c9be6`)한 뒤 같은 입력으로 두 번 실행했다. 입력은 idea "오늘 뭐하지: 전시 정보를 모아 오늘 볼 만한 전시를 추천", effort high, 예산 $10, context `contexts/today-exhibitions`, design auto이다. 두 번 모두 API 크레딧이 떨어져 중간에 멈췄다(`Credit balance is too low`).

### 실행 결과

| run | 코드 | seed | 멈춘 곳 | Plan | Design | Build | 비용 | 시간 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [39113592446](https://github.com/flexda/mvpgen/actions/runs/39113592446) | `69c9be6` Design 단계 병합 직후 | 339168898 (자동) | Design critic | 84, 통과 | 생성만(gate block 0), 채점 없음 | 시작 안 함 | $2.10 | 10분 |
| [39119897521](https://github.com/flexda/mvpgen/actions/runs/39119897521) | `ba75084` 위와 같은 코드, lessons.md 1개 추가 | 339168898 (지정) | Build critic | 72 불합격 -> 90 통과 | 87, 통과(critical 0, minor 6) | 생성, 42턴, 앱 테스트 29개 통과(로컬) | $5.53 | 21분 |

단계별 비용(2차): Plan $1.79(2라운드), Design $1.50, Build $1.79. Design 단계는 실행 비용의 약 27%를 차지했다.

다음 실험의 기준선: 코드 `69c9be6`, seed 339168898. 2차 실행 뒤 `save-lessons`가 교훈 1개를 더 넣었다(`172d3f3`). 그래서 다음 실행은 lessons.md 조건이 이번과 다르다.

로컬 사본: `workspace/ci-39113592446/`, `workspace/ci-39119897521/`(git 제외). 2차 폴더의 `screenshots/`에 데스크톱 1280px과 360px 화면이 있다.

### 디자인 결과

후보 8개는 bmw-m, bugatti, cal, linear.app, nerdwallet, nike, nvidia, opencode.ai였다. 두 실행 모두 B(bmw-m, "폐막일까지의 레이스, 타이밍 타워")를 골랐다.

| 방향 | 원천 | 1차 | 2차 |
| --- | --- | --- | --- |
| A 기준안 | cal | 흰 바탕 캘린더 카드 | 같음 |
| B 의외안 (선택) | bmw-m | 종료일 순 순위표, 레이스 깃발 6색으로 상태 표시 | 종료일 순 순위표, 3색 스트라이프를 추천 점수 세 항목(+1/+2/+3)의 범례로 사용 |
| C 의외안 | 1차 opencode.ai + linear.app, 2차 opencode.ai + nerdwallet | 터미널 이슈 트래커 | 판정 로그와 비교표 |

같은 seed에서 같은 원천과 은유가 나왔지만 세부 장치(깃발 대 스트라이프)와 C안은 달랐다. 2회뿐이라 안정성은 판단하지 않는다.

생성된 앱(2차, 2026-10-18 기준일로 로컬 실행): 검정 바탕에 큰 날짜, 3색 띠, P1~P3 추천 카드(D-n과 점수 띠), 종료일별로 묶은 진행 중 목록. 흔한 카드 그리드 + 필터 형태와는 다르다. playwright 뷰포트 360px에서 `innerWidth`와 `scrollWidth`가 모두 360이라 가로 넘침은 없었다.

### 확인된 것

| 항목 | 상태 |
| --- | --- |
| critic 불합격 후 개정 | 처음으로 실제 발생. Plan 1차 72점(critical 1) -> 2차 90점 |
| 10분 이상 실행 시 토큰 갱신 | 확인. 21분 실행에서 인증 오류 없음 |
| `save-lessons` 잡 | 확인. 1차 실행 뒤 main에 `ba75084` 커밋 |
| Design gate block | 두 번 모두 0회. 차단 경로는 여전히 오프라인 테스트로만 확인 |
| Build critic의 DESIGN.md 준수 평가 | 미확인. 크레딧 부족으로 실행되지 않음 |
| 최종 검증(install/test/smoke) | Actions에서는 미실행. 로컬에서 앱 테스트와 첫 화면 응답만 확인 |

### 드러난 문제

| 문제 | 근거 |
| --- | --- |
| 실행이 중간에 멈추면 이어 할 방법이 없다. 워크플로에 `--resume` 입력이 없고, 남은 단계만 다시 돌리려 해도 처음부터 실행해야 한다 | 두 실행 모두 크레딧 부족으로 중단 |
| 예산 `--budget`은 SDK 추정치 상한이라 실제 크레딧 잔액을 모른다. 잔액이 먼저 바닥나면 단계 중간에 끊긴다 | 2차는 $5.53에서 중단(예산 $10) |
| Design critic이 짚은 minor 6개(파랑 두 색의 대비 1.14:1, D-100 이상 숫자 폭, 범례 위치 중복, 'P1' 용어 등)는 Build로 넘어가지만 반영 여부를 확인할 단계가 실행되지 않았다 | `reviews/design-r1.json` |

### 결정 과정

| 순서 | 질문이나 제안 | 결정 | 버린 안과 이유 |
| --- | --- | --- | --- |
| 1 | PR 병합 | 사용자가 직접 `gh pr merge 1 --rebase` 실행. Claude Code auto mode가 리뷰 없는 병합으로 보고 막았다 | 차단 우회: 하지 않음 |
| 2 | 1차 실패 후 구독(Pro)으로 바꿀 수 있나 | 문서로 확인: 로컬에는 `ANTHROPIC_API_KEY`가 없어 `unset`이 필요 없고, Actions는 WIF라 `CLAUDE_CODE_OAUTH_TOKEN`(우선순위 5, WIF는 6)을 넣어야 바뀐다. 사용자가 크레딧 충전을 택함 | 구독 토큰: 사용 한도로 중간에 멈출 수 있고, SDK 문서가 제3자 제품의 claude.ai 로그인 제공을 금지한다(본인 학습용 해당 여부는 미확인) |
| 3 | 재실행 입력 | 1차와 같은 입력에 `design_seed=339168898`을 지정해 같은 후보를 재현 | 새 seed(1차와 비교 불가) |
| 4 | 2차 결과 보관 | 1번 안: `workspace/ci-<run>/`에 보관하고 이 ARCHIVE에 적재 | Build critic만 다시 받기($5~6 추정, 처음부터 재실행 필요) |
| 5 | 기록을 main에 남길까 | PR #2로 병합. 다음 보완 실험의 기준선이 main에 있어야 전후 비교가 이력으로 이어진다 | 브랜치에만 두기(다음 세션이 찾지 못함) |
| 6 | Actions 대신 로컬에서 싸게 실험할 수 있나 | 지금 코드로는 안 된다. `detect_auth()`가 구독 로그인을 인정하지 않는다. 다음 세션 첫 작업 후보로 둠 | 바로 고치기(점검 단계라 사용자가 정할 일) |

### 인증 설계에서 빠진 안내

| 항목 | 내용 |
| --- | --- |
| 사실 | 10-12 SDK 사용 설계 때 사용자는 API 키 설정만 안내받았다. Pro 구독으로 로컬에서 돌릴 수 있다는 것과 CI용 구독 토큰(`claude setup-token`, `CLAUDE_CODE_OAUTH_TOKEN`)은 안내받지 못했다 |
| WIF를 고른 이유 | Actions에서 API 키 없이 돌리는 다른 방법이 있어서 사용자가 골라 써 본 것이다. WIF도 비용은 API 크레딧에서 나간다 |
| 결과 | mvpgen은 API 방식 인증만 받도록 만들어졌다. `src/mvpgen/identity.py`의 `detect_auth()`는 API 키, AUTH 토큰, 클라우드 제공자, 프로필, federation만 인정하고, 없으면 `cli.py`가 실행 전에 종료한다. 그래서 지금까지의 모든 실행이 크레딧을 썼다 |
| 원인 | 설계 단계에서 Claude가 인증 선택지(구독 로그인, 구독 토큰, API 키, WIF)를 비용 차이와 함께 보여 주지 않았다 |
| 재발 방지 | Claude memory `auth-options-briefing`: 인증, 실행 위치, 비용을 정하기 전에 선택지 표를 먼저 안내한다. SDK 문서의 "제3자 제품은 claude.ai 로그인을 제공하지 말라"는 주의와, 본인 학습용 해당 여부가 미확인이라는 점도 함께 알린다 |
| 다음 할 일 후보 | `detect_auth()`가 구독 로그인과 `CLAUDE_CODE_OAUTH_TOKEN`을 인정하게 고친다. 그 뒤 로컬에서 `/status`로 구독 사용을 확인한다 |

## 2026-10-18: 구독 인증과 단계별 모델

앞 절의 "다음 할 일 후보"를 처리하고, 새 실험을 위해 아키텍처를 살펴본 뒤 단계별 모델 설정을 넣었다. 실험은 아직 하지 않았다.

### 바뀐 것

| PR | 커밋 | 내용 | 검증 |
| --- | --- | --- | --- |
| #4 | `b57cb52` | `detect_auth()`: 우선순위 5에 `CLAUDE_CODE_OAUTH_TOKEN`, 마지막에 `/login` 구독 로그인. 구독 로그인은 SDK 번들 CLI(2.1.294)의 `claude auth status --json`으로 확인하고 `authMethod == "claude.ai"`일 때만 인정한다. `user_oauth` 활성 프로필은 `/login`보다 뒤로 둔다. 토큰은 생성된 앱 환경에서 빼고 명령 가드로 막는다 | 테스트 99개 통과. 로컬 실제 결과 `구독 로그인 (claude.ai, pro)` |
| #5 | `e5786a9`, `3ad0329` | `--stage-model STAGE=MODEL`(여러 번). STAGE는 plan, design, build(build-fix 포함), critic(세 critic 모두), plan-critic, design-critic, build-critic. 세션별 실제 모델은 `runs[].model`, 지정값은 `stage_models`에 남는다. README에 추천 조합 | 테스트 102개 통과. 실제 에이전트 실행으로는 미확인 |

### 아키텍처 확인 (실험 설계용)

| 질문 | 답 |
| --- | --- |
| 에이전트 수 | 7종: plan, plan-critic, design, design-critic, build, build-fix, build-critic. 시스템 프롬프트는 4개(critic 셋이 `CRITIC_SYSTEM` 공유) |
| 병렬 처리 | 없다. 모든 세션이 순차 실행된다 |
| 모델 | PR #5 전에는 `--model` 하나가 모든 단계에 적용 |
| 디자인 | `--design`, `--design-seed`, `--design-candidates`로 직접 조정. 가장 독립적으로 바꿀 수 있다 |
| 데이터 출처, 추천 개수 | mvpgen 옵션이 아니다. Plan이 아이디어, `--context`, `mvp.env` 키 이름을 보고 `spec.json`에 정한다. 기준선은 MMCA API 동기화와 "오늘의 추천 Top 3" |
| 단계 단독 실행 | 옵션이 없다. `--resume`은 통과한 단계를 건너뛸 뿐이다. 앞 단계를 바꾸면 뒤 단계가 모두 바뀐다 |

추천 조합(실험 전 가설): plan, design, build-critic은 `claude-opus-5-5`, build(build-fix 포함)와 plan/design critic은 `claude-sonnet-5-5`. 토큰을 가장 많이 쓰는 Build를 절반 가격 모델로 내리고, 최종 판정은 만든 모델과 다른 Opus에 맡긴다. 구독에서 모델별로 사용 한도가 얼마나 줄어드는지는 문서에 없어 미확인이다.

### 로컬 실행 시도

| 항목 | 내용 |
| --- | --- |
| 목적 | 구독 인증이 실제 실행에서 동작하는지 확인하고, 기준선 입력(seed 339168898)으로 완주 |
| 결과 | 첫 출력 `Claude 인증: 구독 로그인 (claude.ai, pro)` 확인. Plan 1라운드 중 사용자가 중단 |
| 남은 것 | `workspace/20261018-205446-mvp/`(`context/`, `logs/`만 있음). 지우지 않음 |

### 결정 과정

| 순서 | 질문이나 제안 | 결정 | 버린 안과 이유 |
| --- | --- | --- | --- |
| 1 | 첫 작업 | `detect_auth()` 구독 인정(PR #4). 사용자가 브라우저에서 rebase 병합하고, Claude가 PR에 병합 기록 comment를 남김 | 없음 |
| 2 | 로컬 보완 실험 시작 | 원래 checkout은 worktree 격리 규칙 때문에 Claude가 전환할 수 없어, worktree를 main에 맞춰 기준선 입력으로 실행 | 원래 checkout에서 실행: 세션이 접근 불가 |
| 3 | 실행 중 "멈춰" | 즉시 중단. 무슨 실험이냐는 질문에 "보완 내용은 정하지 않았고 기준선 완주 겸 인증 확인이었다"고 답함. 순서를 확인받지 않고 정한 것이 문제였다 | 계속 실행 |
| 4 | 새 실험 방향 | 사용자가 모델, 디자인, 데이터, 추천 개수를 조정하는 실험을 하겠다고 함. 먼저 아키텍처 조사(위 표) | 바로 실행 |
| 5 | 무엇부터 만들까 | 단계별 모델 설정(PR #5) | 단계 단독 실행(`--stop-after`): 다음 후보로 남김 |
| 6 | 단계별 모델 추천과 설정 | 추천 조합을 README에 두고, 기본값은 바꾸지 않음 | 기본값 변경: 전부 Opus인 기준선과 비교할 수 없게 됨. Haiku critic: 판정 품질 위험 |
| 7 | PR #5 병합 | auto mode가 `gh pr merge`를 막아 사용자가 직접 실행 | 차단 우회: 하지 않음 |
| 8 | 실험 순서 | C: 지금은 실행하지 않음 | A: 전부 Opus 기준선을 완주한 뒤 추천 조합과 비교(변수 하나만 바꾸는 안, 2회). B: 추천 조합만 1회 |

### 다음 할 일 후보

- 원래 checkout을 main으로 전환하고 pull
- 실험 A안: 전부 Opus로 기준선을 완주한 뒤 추천 조합 실행
- 단계 단독 실행 옵션(`--stop-after`)
- Actions 워크플로에 `stage_models` 입력 추가

## 2026-10-19: 데이터 파이프라인 모드 (mvpdata)

사용자가 "mvpgen에 API 정보를 넘기면 Supabase에 데이터 파이프라인을 만드는 에이전트"를 새 worktree에서 실험하기로 했다. worktree는 `/Users/reflectdata/Project/loop-2-supabase`, 브랜치는 `exp/supabase-pipeline`(main `2c12e34`에서 분기)이다.

### 만든 것

| 파일 | 내용 |
| --- | --- |
| `src/mvpgen/data_cli.py` | `mvpdata` 진입점. `mvpgen`에 두 번째 명령을 더하면 `mvpgen "아이디어"` 형식이 깨져 별도 script로 뒀다 |
| `src/mvpgen/datapipe.py` | `Pipeline`을 물려받은 `DataPipeline`. 단계 data-plan, data-build, 최종 검증 |
| `src/mvpgen/dataspec.py` | `pipeline.json` 스키마(원천, raw/core/mart 테이블, 품질 검사 SQL, 명령)와 Plan 검사 |
| `src/mvpgen/dbverify.py` | LLM 없는 DB 검사: 마이그레이션 잠금, install/test, `supabase db push`, 테이블 확인, 적재 2회 행 수 비교, 품질 SQL. 근거는 `db/*.md` |
| `src/mvpgen/data_prompts.py` | 데이터 모드 전용 프롬프트와 루브릭. 앱 모드 프롬프트의 "별도 DB 금지", "실행 중 API 호출 금지"와 충돌해 섞지 않았다 |
| 기존 파일 | `RunConfig.extra_secrets`(가드에 DB 비밀값 추가), `_critic_prompt` 교체 지점, `RoundTracker(rollback=False)`, `model_for`가 `*-fixN`을 각 build로 매핑 |
| `contexts/mmca-api/` | 첫 실험용 자료. MMCA API 문서만 둔다 |
| `secrets/supabase.env.example` | `SUPABASE_DB_URL` 형식 |

| 사전 점검 | `mvpdata`가 Claude를 부르기 전에 DB 접속과 상태를 본다. 새 실행은 마이그레이션 기록과 raw/core/mart가 없어야 하고, 이어하기는 기록이 `db/ledger.json`과 같아야 한다 |
| 잠금 자기 검사 | push가 성공했는데 적용 기록에 없는 파일이 있으면 실패로 본다. 버전 형식 가정이 틀려 아무것도 잠기지 않는 일을 막는다 |
| `scripts/smoke_mvpdata.py` | LLM 없이 실제 DB 경로를 확인하는 가짜 앱 검사. 빈 프로젝트에서만 돌고, 끝나면 자기가 만든 raw, core와 기록 한 줄을 지운다 |

테스트 124개 통과(새 22개). 모두 가짜 DB와 가짜 `db push`로 돌았다. 실제 Supabase와 에이전트 실행은 아직 하지 않았다.

A안의 결과로, 같은 프로젝트에서 두 번째 실행을 하면 첫 실행의 기록과 테이블이 남아 사전 점검에서 멈춘다. 실행 사이 정리 방법(실행마다 새 프로젝트 또는 사용자가 직접 돌리는 초기화 명령)은 사용자가 정한다.

### 확인한 사실

| 항목 | 내용 | 출처 |
| --- | --- | --- |
| 마이그레이션 관리 | 파일은 `supabase/migrations/<시각>_이름.sql`로 git에서 관리하고, DB는 `supabase_migrations.schema_migrations`에 적용 기록을 남긴다. `db push`는 적용하지 않은 파일만 실행한다 | Supabase 문서(Database migrations, CLI workflows) |
| CLI 옵션 | 설치된 CLI 2.40.7의 `db push`에 `--db-url`(퍼센트 인코딩 필요), `--workdir`, `--dry-run`, `--yes`가 있다 | `supabase db push --help` |
| 작업 폴더 | `config.toml` 없이 `supabase/migrations`만 있어도 `db push`가 DB 접속 단계까지 간다 | 가짜 주소로 `--dry-run` 실행 |
| 오류 출력 | 접속 실패 메시지에 호스트와 사용자 이름이 나오고 비밀번호는 나오지 않는다. 그래도 mvpgen은 가린다 | 같은 실행 |
| 로컬 도구 | Supabase CLI는 `~/.local/bin/supabase`에 있고, Docker는 설치되어 있지만 데몬이 꺼져 있다. psql은 없다 | `which`, `docker info` |

미확인: `schema_migrations.version`이 파일 이름의 14자리 시각과 같은 값인지(잠금이 이 가정을 쓴다), MMCA API 일일 호출 한도, Session pooler에서 `db push`가 동작하는지. 첫 실제 실행에서 확인한다.

### 결정 과정

| 순서 | 질문이나 제안 | 결정 | 버린 안과 이유 |
| --- | --- | --- | --- |
| 1 | 구성 방식 | 독립 모드 | 기존 흐름의 새 단계(Plan -> Data -> Design -> Build): 실행 비용과 변경 범위가 크다 |
| 2 | Supabase 위치 | 클라우드 프로젝트 | 로컬(`supabase start`, Docker): 추천했으나 사용자가 클라우드를 골랐다 |
| 3 | API 정보 입력 | `--context` 폴더 | CLI 인자(`--api-url` 등): 문서 없이 에이전트가 응답을 탐색해야 한다 |
| 4 | 검사 때마다 스키마를 지우고 다시 만들기 | 사용자가 "정식으로 쓰면 SQL 파일이 없어지나"라고 물음. 없어지지 않고, 지우기는 개발 중 편법이었다고 설명 | 없음 |
| 5 | 마이그레이션 방식 | A: 정식 규칙(잠금 + 새 파일 추가) | B: 매번 초기화. 최종 SQL만 보고, 변경을 누적하는 능력은 보지 못한다 |
| 6 | 프로젝트 | 실험 전용 새 프로젝트 | 기존 프로젝트: A안이라 위험은 작지만 정리가 번거롭다 |

### 사용자가 할 일

1. supabase.com에서 새 프로젝트를 만든다.
2. 대시보드 Connect > Session pooler 문자열을 main checkout의 `secrets/supabase.env`에 `SUPABASE_DB_URL=...`로 넣는다. 비밀번호의 특수문자는 퍼센트 인코딩한다.
3. 첫 에이전트 실행 전에 `scripts/smoke_mvpdata.py`로 실제 DB 경로를 확인한다(확인받은 뒤).
4. 실행은 확인받은 뒤 worktree에서 `uv run mvpdata ... --secrets /Users/reflectdata/Project/loop-2-test/secrets`로 한다(worktree에는 실제 secrets가 없다).

## 커밋

| 시각 | 커밋 |
| --- | --- |
| 14:12 | `1335886` mvpgen 최초 커밋 |
| 15:36 | `6271342` 워크플로 `runner.temp` 수정 |
| 15:38 | `ebb6563` API 오류 시 즉시 중단 |
| 15:45 | `bf71bdb` `export PORT` 실행 안내 수정 |
| 10-13 | `7f1a5bd` Plan 의도 검증, `-mvp` 폴더 이름 변경 |
| 10-13 | `df0367c` `--context` 참고 자료 |
| 10-13 | `e2c241e` 참고 자료 `contexts/today-exhibitions` |
| 10-13 | `6ca8790` `lessons.md` 저장소 보관과 `save-lessons` 잡 |
| 10-18 | `b57cb52` `detect_auth()` 구독 로그인과 `CLAUDE_CODE_OAUTH_TOKEN` 인정 (PR #4) |
| 10-18 | `e5786a9` `--stage-model` 단계별 모델 (PR #5) |
| 10-18 | `3ad0329` README 단계별 모델 추천 조합 (PR #5) |
