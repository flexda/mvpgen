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
| 의외성의 뜻 (2026-10-19) | 다른 분야의 디자인 언어를 옮기는 것이 아니다. 같은 분야(전시 세계) 안의 낯선 표현과, 오늘 볼 전시를 고르는 방식의 의외성이다. 10-18 "디자인 방향" 결정을 이렇게 좁힌다 | 사용자 판단. 기준선(bmw-m 레이싱 화면)이 "너무 안 어울린다" |
| 디자인 참조 (2026-10-19) | 시안의 색, 글꼴, 레이아웃은 그 분야 실제 기관 사이트의 CSS 실측값과 화면 캡처에서 가져온다 | 참조 없이 만든 1차 시안을 사용자가 "디자인이 전혀 안 바뀐 느낌"이라고 함 |
| 시안 비교 방식 (2026-10-19) | 디자인과 고르는 방식(기능 구조)을 따로 바꿔 3 × 3으로 비교한다 | 둘을 묶은 시안으로는 선호 이유를 나눌 수 없었다 |
| 선호 디자인 (2026-10-19) | C(Stedelijk 참조). 고르는 방식은 미정 | 사용자 선택 |
| 실험 반영처 (2026-10-19) | 이 디자인 실험의 발견은 아키텍처 개선에 반영한다 | 사용자 결정 |
| 목표 흐름 (2026-10-19) | 인터뷰(brief) -> PRD -> spec 후보 -> 조사 -> 거르기 -> 디자인 미리보기 -> 사람의 선택 -> DESIGN.md -> Build -> 검증 | 사용자가 제시한 아키텍처. 브랜치 `exp/architecture` |
| 인터뷰 위치 (2026-10-19) | Claude Code 세션의 `/grilling`으로 인터뷰해 `brief.md`를 쓰고 `--brief`로 넘긴다 | 파이프라인 세션은 사람에게 질문을 되돌릴 통로가 없다(`setting_sources=[]`, `dontAsk`) |
| 사람의 선택 (2026-10-19) | spec critic은 거르기만 하고, 사람이 고르는 방식(spec 후보)과 디자인 방향을 한 번의 멈춤에서 따로 고른다 | 의외성의 절반이 고르는 방식에 있다. critic은 실행 가능성으로 채점해 무난한 쪽으로 기운다 |
| spec 후보의 축 (2026-10-19) | 후보는 사용자가 겪는 고르는 방식으로 나눈다. 기능 id는 같게 둔다 | 기술 결정으로 나누면 사람이 데이터 출처를 고르게 된다 |
| 디자인 critic (2026-10-19) | 없앤다. 대비, 외부 리소스, 기능 대응은 코드 검사로 한다 | 사람이 미리보기로 고르므로 취향 판단이 겹친다. 기계적 조건은 코드가 더 정확하다 |
| 의외성 정의 (2026-10-19) | 이 앱의 분야에 어울리는 스타일 가운데 흔하지 않은 표현 | 디자인 실험 결론(같은 분야 안의 낯선 표현)을 원천 종류에 맞게 일반화 |
| 디자인 원천 (2026-10-19) | 무작위 추출을 없애고, DESIGN.md 레퍼런스 사이트에서 웹 검색 범위를 제한해 찾는다. 실패하면 로컬 라이브러리 | 무작위 추출은 옛 의외성 정의(다른 분야 빌리기)를 위한 장치였다. 사용자 제안 |
| Actions 디자인 기본값 (2026-10-19) | `off`, 고르는 방식은 critic 추천 | 사람의 선택을 기다리는 흐름은 Actions 한 번의 실행과 맞지 않는다. 사용자 선택 |
| 데이터 파이프라인 모드 (2026-10-19) | API 자료를 받아 Supabase 적재 파이프라인을 만드는 독립 모드 `mvpdata`. 기존 Plan/Design/Build 흐름은 그대로 둔다 | 사용자 선택. 목적은 mvpgen이 외부 DB 적재까지 할 수 있는지 보는 것. 브랜치 `exp/supabase-pipeline` |
| 적재 대상 (2026-10-19) | 클라우드 Supabase 실험 전용 새 프로젝트 | 사용자 선택. 프로젝트 생성과 접속 문자열 입력은 사용자가 한다 |
| API 정보 입력 (2026-10-19) | 기존 `--context` 폴더 재사용, 키는 `mvp.env` | 사용자 선택. 비밀값 검사 로직을 그대로 쓴다 |
| 마이그레이션 방식 (2026-10-19) | Supabase 정식 규칙: 적용한 파일은 잠그고 변경은 새 파일로 추가. 적용은 `supabase db push --db-url` | 사용자 선택(A안). 검사마다 스키마를 지우고 다시 만드는 B안은 정식 흐름과 달라 버림 |
| 데이터 모드 API 호출 제한 (2026-10-19) | 에이전트 세션에 API 키를 주지 않고, Plan 뒤 오케스트레이터가 `source.sample`대로 샘플을 받아 `context/samples/`에 둔다. install, test에도 키를 주지 않는다 | 첫 실행에서 에이전트가 자기 셸로 전체 수집을 여러 번 해 페이지 제한이 새었다. 사용자 승인 |
| 데이터 모드 major 불합격 (2026-10-19) | major 이슈가 남으면 critic 점수와 상관없이 불합격, 개정 한도 뒤에도 남으면 실행 실패. 앱 모드 판정은 그대로 | 첫 실행에서 다른 전시를 합치는 major가 83점으로 합격했다. 사용자 승인 |
| MMCA 2차 실행 (2026-10-20) | 구독 한도로 두 번 끊긴 뒤 중단. 보강 동작 검증은 다음 새 API 실행에 맡긴다 | 사용자 결정. 원래 실험 질문은 1차로 답이 났다 |

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

## 2026-10-19: 디자인 의외성 재검토 (시안 실험)

worktree `/Users/reflectdata/Project/loop-2-design`(브랜치 `exp/design`, main `2c12e34`에서 분기)에서 했다. mvpgen은 실행하지 않았고, 정적 HTML 시안만 만들었다. 시안은 `docs/design-mockups-2026-10-19/`에 있고, `index.html`이 비교 페이지다.

### 진행

| 순서 | 작업 | 결과 |
| --- | --- | --- |
| 1 | 기준선 요약 | run 39119897521, seed 339168898, bmw-m(B안) 선택, Build critic에서 중단 |
| 2 | 의외성의 뜻 확인 | 사용자 답: 같은 분야 안의 낯선 표현 + 고르는 방식의 의외성 |
| 3 | 1차 시안 3개(리플릿, 입장권, 벽면 캡션) | 실패. 참조 없이 만들어 색과 디자인 요소가 거의 같았다. 파일은 지움 |
| 4 | 참조 다시 수집 | 미술관 사이트 12곳의 홈 HTML과 CSS에서 색, 글꼴 빈도를 세고 1280px 화면을 캡처. New Museum, Barbican, Stedelijk를 고름 |
| 5 | 2차 시안 3개 | 디자인이 실제로 달라짐. 사용자가 C(Stedelijk)를 선호 |
| 6 | 디자인과 방식 짝짓기 점검 | 짝지은 근거가 사후에 붙인 것이었다. 둘이 섞여 선호 이유를 나눌 수 없었다 |
| 7 | 디자인 3 × 방식 3 = 9개 페이지 | 고르는 규칙은 `logic.js`(C는 페이지 안), 디자인은 CSS 3개. 360px과 1280px에서 가로 넘침 없음, 버튼 동작 확인 |
| 8 | DESIGN.md 반영 경로 확인 | `--design <경로>`로 지정할 수 있다. 다만 그 파일은 Design critic을 거치지 않는다(`pipeline.py` `design()`) |

### 참조 실측 (2026-10-19 조회)

| 사이트 | CSS에 많이 쓰인 색 | 글꼴 | 판단 |
| --- | --- | --- | --- |
| New Museum | #000 #fff #00b2ff #beff00 | Akkurat, Neographik | 채택 A |
| Barbican | #333 #d14900 #fff | Supreme | 채택 B |
| Stedelijk | #fff #0a0a0a #ebeae8, 화면에 #22ff06 #ffd511 | Union | 채택 C |
| Whitney | #000 #ccc #fff #d7ff2d | Neue Haas Grotesk | Stedelijk와 겹침 |
| ICA | #fff #000 #ffff00 #ff0000 #0000ff | OCR-B, Computer Modern | 후보 |
| Palais de Tokyo | #fff #000 #fff8a5 | Silka, Gaffer | A와 겹침 |
| Kunsthalle Basel, MoMA | 흑백 위주 | Suisse, MoMA Sans | 보류 |
| Serpentine, Walker, 아트선재, 리움 | 추출 실패 또는 워드프레스 기본색 | - | 보류 |

글꼴은 대체품을 썼다(Archivo, Black Han Sans, Outfit, Pretendard, Helvetica Neue). 참조 사이트 화면 캡처는 다른 기관의 화면이라 저장소에 넣지 않았다. 비교 페이지에는 사이트 링크만 둔다.

### 고르는 방식 3가지

| 방식 | 사용자가 하는 일 | 규칙 | 10-18 결과 | 바꿀 곳 |
| --- | --- | --- | --- | --- |
| 1 추천 Top 3 | 없음 | 기준선 F4 점수 상위 3개, 갤러리당 1개 | 박서보, Moon Mind, Míope | Design만 |
| 2 시간 동선 | 2시간/반나절/하루 | 오늘 닫는 전시가 많은 동네부터 시간 안에 채움 | 반나절: 삼청·북촌 5곳, 약 3.5시간 | Design + Plan F4 + 데이터(동네, 관람 시간) |
| 3 질문형 | 오늘 아니면 못 봄 / 이번 주 / 급하지 않음 / 전부 | 점수 없이 남은 날로 나눔 | 오늘: 4건 | Design + Plan F4 |

2번의 동네와 관람 시간은 확인하지 않은 시안용 가정이다.

### 아키텍처에 반영할 발견

| 발견 | 근거 | 영향받는 곳 |
| --- | --- | --- |
| "분야가 다른 후보" 규칙이 어울리지 않는 디자인을 만든다 | 기준선 레이싱 화면, 사용자 판단 | `DESIGN_SYSTEM` 프롬프트 |
| design-library에 분야에 맞는 원천이 없다 | 86개 모두 일반 브랜드, 전시 기관 0개 | design-library, 후보 추출 규칙 |
| 참조 없이 만든 디자인은 무난하게 수렴한다 | 1차 시안 실패, 실측 참조를 쓴 2차는 달라짐 | 참조 수집 단계 |
| 디자인과 고르는 방식이 다른 단계에 있다 | 고르는 방식은 spec F4라 Design 단계가 바꿀 수 없다 | Plan과 Design의 경계 |
| 디자인과 구조를 한 시안에 묶으면 평가가 섞인다 | C 선호 이유를 나눌 수 없었다 | concepts.json의 시안 구성 |
| 지정한 DESIGN.md는 critic을 건너뛴다 | `pipeline.py` `design()`의 `provided` 분기 | Design 검사 경로 |
| 기준선 F4의 갤러리당 1개 규칙이 오늘 닫는 전시를 뺀다 | 「Pictos and Pitwall」(국제갤러리 K2, 10-18 종료) 누락 | Plan의 F4 검증 |

### 결정 과정

| 순서 | 질문이나 제안 | 결정 | 버린 안과 이유 |
| --- | --- | --- | --- |
| 1 | Design 실험 worktree | `exp/design`을 `loop-2-design`에 새로 만듦(이전 같은 경로 worktree는 이미 지워져 있었음) | 원래 checkout에서 작업: 다른 실험(`exp/architecture`)과 섞임 |
| 2 | 의외성이 어떤 뜻인가 | 같은 분야 안의 낯선 표현 + 고르는 방식(사용자가 보기 4개 중 2, 3번 선택) | 어울리되 한 군데만 새로움, 작품 중심 갤러리형 |
| 3 | 시안을 어떻게 볼까 | 정적 HTML 시안(기준선 앱의 10-18 데이터 사용) | Design 프롬프트를 고쳐 mvpgen 실행: 시간과 사용량이 큼, 점검 단계 |
| 4 | 1차 시안 반응 "디자인이 전혀 안 바뀐 느낌" | 참조 수집부터 다시. 실제 기관 사이트 CSS 실측 | 1차 시안 다듬기: 원인이 참조 부재라 해결되지 않음 |
| 5 | 짝지은 이유가 있나 | 근거가 약했다고 답하고, 디자인과 방식을 분리하자고 제안 | 그대로 유지: 선호 이유를 나눌 수 없음 |
| 6 | 비교 범위 | C에 방식 3개, 이어서 A, B에도 방식 3개(총 9개) | - |
| 7 | 결정되면 DESIGN.md를 새로 쓰나 | 디자인만이면 DESIGN.md + `--design`, 방식까지면 Plan(F4) 전달이 필요, 파이프라인 일반화는 library와 프롬프트 수정 | - |
| 8 | 이 실험의 쓰임 | 아키텍처 개선에 반영 | - |

### 남은 것

- 고르는 방식 결정
- Plan에 spec을 고정해서 넣는 옵션이 있는지 확인(미확인. `pipeline.py` `plan()`과 `cli.py` 옵션 확인)
- 2번 방식을 쓰면 갤러리 동네와 관람 시간 데이터 확인

## 2026-10-19: 아키텍처 개선 (exp/architecture)

worktree `/Users/reflectdata/Project/loop-2-arch`(브랜치 `exp/architecture`)에서 했다. 사용자가 목표 흐름을 제시했고, 단계를 커밋 하나씩 쌓았다. 커밋마다 테스트가 모두 통과한 상태로 남겼다(최종 155개, 가짜 에이전트).

### 바뀐 것

| 커밋 | 내용 |
| --- | --- |
| 단계 표 | plan, design, build 하드코딩을 `STAGES` 표로 옮김. 동작 변화 없음 |
| 멈춤과 재개 | 사람이 고를 차례면 `awaiting_choice`로 멈추고 종료 코드 3. `--resume`은 처음 실행의 설정(모델, 예산 등)을 이어 씀 |
| brief | `--brief brief.md`. 있으면 PRD, Spec, critic이 아이디어 한 줄보다 먼저 읽음. 없으면 프롬프트가 예전과 같음 |
| PRD와 spec 분리 | PRD는 무엇과 왜만(수치 없음), spec은 후보 2개. 예전 `plan` 키와 `[plan]` 교훈은 별칭으로 이어 씀 |
| 조사 | 후보마다 웹 조사 세션이 `research/<id>.md`를 씀. 셸 없음, 자기 파일만 씀, URL과 검색어의 비밀값 차단 |
| 거르기와 두 선택 | spec critic은 viable, 점수, 추천만. 사람이 `--choose-spec`과 `--choose-design`을 이유와 함께 따로 줌 |
| 미리보기와 코드 검사 | 방향마다 `previews/<id>.html`(중립 구조, 실제 데이터). 대비 4.5:1, 외부 리소스, `data-feature`를 코드로 검사. 디자인 critic 삭제 |
| 고르는 방식 축, 무작위 제거 | spec 후보는 고르는 방식으로 나눔. 디자인 원천은 라이브러리 전체와 INDEX에서 에이전트가 고름 |
| 레퍼런스 원천 | `design-sources.toml`의 레퍼런스 저장소 안에서만 웹 검색하고, 코드가 원본을 내려받음. 출처를 DESIGN.md에 남김 |
| 문서 | README, 워크플로 기본값 `off` |

### 실제 실행 (시험용, 할 일 앱)

새 흐름이 실제 모델에서 동작하는지 보려고, 작고 외부 키가 필요 없는 아이디어로 돌렸다. 모델은 Sonnet 5.5 하나, design auto, `--choose-spec recommended`, 예산 $3. 로컬 구독(Pro).

| 세션 | 비용 | 결과 |
| --- | --- | --- |
| prd, prd-critic | $0.28, $0.29 | 1라운드 합격 |
| spec (후보 2개) | $0.41 | gate block 0. a는 한 장짜리 목록, b는 "지금 할 일 하나"에 집중 |
| research-a, research-b | $0.50, $0.39 | WebFetch는 구독에서 동작. WebSearch는 한 번도 쓰지 않음 |
| spec-screen-critic | $0.23 | 둘 다 viable(86점, 72점), a 추천, 교훈 4개 |
| design-directions | $0.79 | 방향 3개와 미리보기가 검사를 한 번에 통과 |
| 합계 | $2.88 | 디자인 선택 대기에서 멈춤(종료 코드 3) |

이 실행은 Build까지 이어 가지 않았다. 목적(새 형식이 동작하는지)은 이뤘고, 비교 대상은 할 일 앱이 아니라 오늘 뭐하지다. 레퍼런스 원천(5b)은 이 실행 뒤에 만들어 아직 실제로 돌려 보지 않았다.

### 레퍼런스 사이트 조사

| 사이트 | 판단 | 이유 |
| --- | --- | --- |
| VoltAgent/awesome-design-md | 채택 (web) | MIT, GitHub 원본, 84개 |
| nexu-io/open-design | 채택 (web) | Apache-2.0, 305개 |
| bergside/awesome-design-skills | 채택 (web) | MIT, 67개 스타일 |
| meliwat/awesome-ios-design-md | 채택 (app) | MIT, 앱 200개 |
| Refero Styles | 제외 | 공식 MCP는 유료(Pro 이상). JSON API는 직접 요청 시 403. 다운로드 API 없음. 사용자 계정은 무료 |
| designmd.app | 제외 | 목록과 메타데이터는 공개지만 원본(content)은 토큰이 필요(401). CC BY 4.0 |
| VoltAgent/official-design-md, awesome-claude-design | 보류 | 파일 구조를 확인하지 못함 |
| URL 생성기(designmd.cc 등) | 제외 | API가 없거나 웹 화면 전용 |

첫 조사에서 Refero를 놓쳤다. 검색어를 "DESIGN.md"로만 좁혔고 세 번만 찾은 뒤 전체인 것처럼 정리했다. 다시 찾을 때는 표현을 바꾸고 GitHub에서 직접 확인했다.

### 결정 과정

| 순서 | 질문이나 제안 | 결정 | 버린 안과 이유 |
| --- | --- | --- | --- |
| 1 | 실험을 어디서 하나 | 브랜치와 worktree(`loop-2-arch`) | 같은 폴더 전환: 기준선과 나란히 돌릴 수 없음 |
| 2 | 인터뷰 위치 | Claude Code 세션의 `/grilling` -> `brief.md` | mvpgen 안의 대화형 루프: 통로가 없고 만들 것이 많음 |
| 3 | 사람이 보면 디자인 critic이 필요한가 | 빼고 코드 검사로 바꿈 | Build critic에 넘기기: 대비는 DESIGN.md 토큰 문제라 Build가 고칠 수 없음 |
| 4 | 커밋 순서 | 단계 표부터 한 커밋씩, 단계마다 테스트 통과 | 한 번에 바꾸기: 리뷰와 되돌리기가 어려움 |
| 5 | Actions 기본값 | `off`와 critic 추천(사용자 선택) | 그대로 auto: 기본 실행이 멈추고 이어 갈 수 없음 |
| 6 | PRD와 spec 분리 계획 점검 | 후보는 위험한 결정 하나로 나누고, PRD엔 수치를 두지 않고, 승자 고정 후 spec만 개정 | 스택 차이 강제: 억지 후보. 예전 실행 이어 하기: 이을 실행이 없음 |
| 7 | 웹 도구를 구독에서 쓸 수 있나 | 문서로 확인(WebSearch는 구독과 API 키 모두, bare `WebFetch` allow는 모든 도메인) | |
| 8 | 디자인 실험 결과 반영 | 의외성 정의를 바꾸고 원천을 다시 정함 | |
| 9 | 원천 방식 | 처음엔 사이트 하나와 연동하려 했으나, 사용자 뜻은 "웹 검색 범위를 레퍼런스 사이트로 한정"이었다. 여러 사이트 목록으로 감 | 사이트 하나 고정: 사용자 반대("하나로 교정하지 말고") |
| 10 | 고르는 방식은 누가 고르나 | 사람(새 안) | critic: 의외성의 절반을 보수적인 판정자에게 맡김 |
| 11 | spec 후보 축 | 고르는 방식 | 기술 결정: 사람이 데이터 출처를 고르게 됨 |
| 12 | 무작위 추출 | 없앰 | 유지: 새 의외성 정의와 맞지 않음 |
| 13 | Refero | 제외하고 손으로 넣는 경로(`--design-library`)만 남김 | 유료 MCP: 사용자 계정이 무료 |
| 14 | 시험 실행의 디자인 선택 | Build까지 가지 않고 멈춤 | Claude가 대신 고르기: 사용자가 "왜 할 일 앱이냐"고 물음. 실험 측정값이 될 선택은 사용자 몫 |
| 15 | 작업 방식 | 큰 결정이 아니면 Claude가 정하고 끝까지 진행, 이유는 이 문서에 남김 | |

### 남은 것

- 오늘 뭐하지를 brief와 context로 디자인까지 실제 실행. 멈춤에서 고르는 방식과 디자인은 사용자가 고름
- 레퍼런스 원천의 실제 동작 확인(미확인: GitHub 범위 웹 검색이 파일 단위 DESIGN.md를 찾아 주는지)
- 웹 검색 요금과 SDK 비용 추정 반영 여부(미확인)
- 조사 세션 비용이 큼(시험 실행에서 후보당 $0.4~0.5). `--stage-model research=` 조정 검토

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
| 프로젝트 생성 | CLI가 이미 로그인되어 있어 `supabase projects create mvpdata-test --org-id ... --region ap-northeast-2`로 만들었다(ref `yjucvkpimbnsuicsudtd`). 비밀번호는 생성해 `secrets/`에만 저장했다 | 명령 결과 |
| pooler 주소 | `supabase link`가 `supabase/.temp/pooler-url`에 남기는 주소는 6543(Transaction 모드)이다. 같은 호스트의 5432(Session 모드)로 접속했다 | 명령 결과, psycopg 접속 |
| Session pooler의 `db push` | 동작한다 | smoke 실행 |
| 적용 기록 버전 형식 | `schema_migrations.version`이 파일 이름의 14자리 시각과 같다. smoke에서 잠금이 1개 생겼다 | smoke 실행 |
| 적재와 가리기 | 적재 2회 행 수가 같았고, 품질 SQL이 읽기 전용으로 돌았고, 근거 파일에 비밀값이 없었다. 정리 뒤 기록과 스키마가 비어 사전 점검을 다시 통과했다 | smoke 실행 |

미확인: MMCA API 일일 호출 한도. 에이전트 실행은 아직 하지 않았다.

### 첫 실제 실행 (MMCA, 15:37-16:4x)

명령: `uv run mvpdata "MMCA 전시 정보를 Supabase에 적재" --context contexts/mmca-api --final-pages 5`, 구독 로그인(pro), 결과 폴더 `workspace/data-20261019-153750-mmca-supabase`(git 제외).

| 단계 | 결과 |
| --- | --- |
| data-plan | r1 76점, r2 87점 합격 |
| data-build | r1 83점 합격, Stop gate 1회, DB 검사 2회(check-1, check-2) |
| 최종 검증(5페이지) | 전 단계 통과. core.exhibition_record 500, core.exhibition 184, mart.exhibition_current 25, 2회차 행 수 동일, 품질 검사 11개 위반 0 |
| 마이그레이션 | `20261019160000_mmca_init.sql` 1개 잠김. DB 적용 기록과 같다(직접 조회) |
| 비용 추정 | $9.44 (상한 $10에 근접. 구독이라 청구 없음) |
| 비밀값 | 결과 폴더에 DB 비밀번호 없음(grep) |

관찰:

| 항목 | 내용 |
| --- | --- |
| 페이지 제한 우회 | 페이지 제한은 검사기가 넘기는 적재에만 걸린다. 에이전트가 자기 Bash로 실제 API를 탐색하고, `uv run --with pgserver`로 `/tmp`에 임시 Postgres를 띄워 전체 수집(40페이지)을 여러 번 돌렸다. 호출 수는 세지 않았다. 일일 한도 오류는 없었다 |
| critic 지적(major) | 제목 포함 관계 병합이 다른 전시를 합친다(`한국근현대미술 I`과 `II`). 83점으로 합격했지만 데이터 손실이다 |
| critic 지적(minor) | 1969년 이전 전시 56건을 core에서 뺐다(Plan의 period_order 하한 때문). 전체 수집은 Supabase에서 검증되지 않았다 |
| 정리 | 에이전트가 남긴 `/tmp/mmca_pg`(78MB)와 탐색 파일을 지웠다. 서버 프로세스는 이미 꺼져 있었다 |

이 프로젝트에는 이제 기록과 데이터가 있어 같은 프로젝트로 새 실행을 하면 사전 점검에서 멈춘다.

### 첫 실행 뒤 보강 (API 호출 제한, major 불합격)

| 변경 | 내용 |
| --- | --- |
| `src/mvpgen/datasample.py` | `fetch_samples`: `source.sample`(url, params, headers, pages 1-3, 값의 `{key}`, `{page}`)대로 받는다. 키와 인코딩된 키를 본문과 요청 기록에서 가린다. 2MB 상한, 30초 timeout, certifi 인증서. 성공했을 때만 `README.md`를 써서 실패하면 다음 실행이 다시 받는다 |
| `dataspec.py` | `SampleRequest`. `key_env`가 있으면 `{key}`가 있어야 하고, 없으면 없어야 한다 |
| `pipeline.py` | `_agent_env()`, `_is_accepted()`를 바꿀 수 있는 지점으로 뺐다. 앱 모드 동작은 같다 |
| `datapipe.py` | 에이전트 env 비움, `mvp_env` 값을 가드 비밀값에 추가, Plan과 Build 사이에 API 샘플 단계, major 불합격, `open_major`와 `api_calls`를 보고서에 |
| `dbverify.py` | install, test 환경에서 API 키를 뺐다. 키는 적재 단계에만 들어간다 |
| `data_prompts.py` | 심각도 규칙(major는 이 실행에서 고칠 수 있는 데이터 손실, 멱등, 마이그레이션, 실패 삼킴), 샘플 사용, 키 없음, 로컬 Postgres 금지 |

이어서 고친 것: data-plan 되돌리기를 점수만이 아니라 (합격 여부, major 없음, 점수) 순으로 비교한다(`RoundTracker(rank=)`). 점수만 보면 major를 고친 라운드가 점수가 조금 낮을 때 major가 있는 판으로 돌아간다. 합격한 라운드를 더 높은 점수의 불합격 판으로 되돌리던 기존 동작도 함께 고쳐져 앱 모드에도 적용된다. data-plan에 major가 남으면 Build 전에 멈춘다. 셸에 export한 `mvp_env` 키도 시작할 때 환경에서 지운다. 로컬 Postgres로 마이그레이션을 미리 확인하는 것은 허용한다(키가 없어 실제 API는 못 부르고, 잠긴 뒤 고치는 마이그레이션을 줄인다).

확인: 테스트 133개 통과(새 9개). 실제 MMCA로 샘플 1페이지를 받아 HTTP 200, XML 5096바이트, 파일과 요청 기록에 키 없음을 확인했다(호출 1회).

남은 한계: 키가 필요 없는 API는 에이전트가 직접 부르는 것을 막지 못한다(네트워크 격리 없음). 심각도 기준이 엄해져 개정 라운드가 늘면 기본 예산 $10으로는 부족할 수 있다(첫 실행 $9.44).

### 2차 실행 (MMCA 재실행, 중단)

보강한 동작(키 없는 에이전트, API 샘플, major 불합격)을 실제 실행으로 확인하려고 새 프로젝트 `mvpdata-test2`(ref `exzrrhekiguwhnkyhsmi`, Seoul)를 CLI로 만들고 1차와 같은 목표로 돌렸다. `--budget 20`, 최종 5페이지, 구독 로그인(pro). 결과 폴더 `workspace/data-20261019-163341-mmca-supabase`.

| 시도 | 진행 | 비용 추정 | 결과 |
| --- | --- | --- | --- |
| 10-19 16:33 | data-plan r1 생성, critic 시작 직후 | $2.00 | "You've hit your session limit · resets 7:20pm" |
| 10-19 21:02 이어하기 | data-plan r1을 다시 생성, critic이 review를 쓴 뒤 | +$2.51 | "resets 12:20am" |

사용자 결정으로 여기서 멈췄다. 보강한 동작은 실제 실행으로 확인하지 못했다(미확인). 다음 새 API 실행이 함께 확인한다.

알게 된 것:

| 항목 | 내용 |
| --- | --- |
| 구독 한도 | Pro 세션 한도 한 번에 비용 추정 $2.5-4.5 정도만 돌았다. 1차 전체($9.44)는 운이 좋았거나 한도가 남아 있던 상태였다. 같은 대화의 사용량도 같은 한도를 쓴다 |
| 이어하기 낭비 | 이어하기는 끝나지 않은 라운드를 처음부터 다시 생성한다. critic review가 남아 있어도 data-plan을 다시 만들었다 |
| 프로젝트 | `mvpdata-test2`는 비어 있다(적용 기록 없음). 다음 실행에 재사용한다. 1차 프로젝트 접속 정보는 `secrets/supabase-test1.env`, `secrets/.supabase-db-password-test1`로 옮겼다 |

### 결정 과정 (2차 실행)

| 순서 | 질문이나 제안 | 결정 | 버린 안과 이유 |
| --- | --- | --- | --- |
| 1 | 다음 실험 순서 제안(MMCA 재실행, 새 API, 요구 추가 실행) | MMCA 재실행부터 | 없음 |
| 2 | 한도로 두 번 끊긴 뒤 이어가는 방법(한도마다 이어하기, Sonnet, API 키) | 사용자가 "비교 실험 꼭 해야 해?"라고 물음. 원래 질문(외부 DB 적재 가능 여부)은 1차로 답이 났다고 설명 | 없음 |
| 3 | 2차 실행 | 중단. 보강 검증은 다음 새 API 실행에 맡긴다 | 한도마다 이어하기: 반나절-하루 걸리고 비교 가치가 작다. API 키: 실제 청구 |

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

1. 새 프로젝트와 `secrets/supabase.env`: 완료(사용자 확인 뒤 CLI로 만듦).
2. smoke 확인: 완료, 전 단계 통과.
3. 실행은 확인받은 뒤 worktree에서 `uv run mvpdata ... --secrets /Users/reflectdata/Project/loop-2-test/secrets`로 한다(worktree에는 실제 secrets가 없다).

## 2026-10-21: 실험 브랜치 통합

`exp/architecture`(12커밋)와 `exp/supabase-pipeline`(8커밋)을 main에 합쳤다. `exp/design`은 PR #7로 이미 들어가 있었다.

| 결정 | 내용 | 이유 |
| --- | --- | --- |
| 병합 순서 | architecture 먼저, supabase-pipeline 다음 | architecture가 단계 구조를 바꿨다. mvpdata는 옛 구조 위의 작은 연결 지점이라 새 구조에 맞추기 쉽다 |
| 단계 구조 | architecture의 단계 표(`Stage`)를 기준으로 한다. `Stage`에 `rollback`을 더하고, mvpdata는 `DATA_PLAN`, `DATA_BUILD`를 `Stage`로 정의한다 | 옛 `GEN_TOOLS_*`, `CRITIC_TOOLS_*` 상수와 `_review_loop(rubric=..., critic_tools=...)` 인자가 단계 표로 옮겨졌다 |
| 단계별 모델 | `data-*` 세션은 `data-plan`, `data-build` 키를 따르고 앱 모드의 plan, build 키를 쓰지 않는다. critic은 개별 키, 없으면 `critic` | 단계 표의 이름 규칙(첫 토큰)으로는 `data-plan`이 `data`가 된다 |
| guard | 웹 도메인 범위(architecture)와 추가 비밀값(supabase)을 함께 넘긴다 | 두 기능이 서로 독립이다 |

### 결정 과정

| 순서 | 질문이나 제안 | 결정 | 버린 안과 이유 |
| --- | --- | --- | --- |
| 1 | 통합 방법 | 사용자가 "알아서 병합"을 맡김. `integrate/main`에서 충돌을 풀고 테스트 통과 뒤 main을 앞당김 | main에서 바로 병합: 실패하면 main 작업 폴더가 반쯤 병합된 채 남는다 |
| 2 | `exp/architecture`의 커밋 안 된 `lessons.md` | 같은 지적 두 줄 중 하나만 커밋 | 둘 다: 같은 내용의 중복 |
| 3 | `new-api/` CSV, 세션 내보내기 txt, `loop-2-writing` 미추적 파일 | 커밋하지 않음 | 다음 실험의 입력이거나 다른 실험의 원고다 |

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
