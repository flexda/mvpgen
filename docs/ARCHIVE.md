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

## 커밋

| 시각 | 커밋 |
| --- | --- |
| 14:12 | `1335886` mvpgen 최초 커밋 |
| 15:36 | `6271342` 워크플로 `runner.temp` 수정 |
| 15:38 | `ebb6563` API 오류 시 즉시 중단 |
| 15:45 | `bf71bdb` `export PORT` 실행 안내 수정 |
