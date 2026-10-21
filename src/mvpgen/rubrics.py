"""단계별 critic 루브릭."""

PRD_RUBRIC = """\
1. 아이디어의 핵심 가치: PRD가 사용자가 말한 아이디어의 핵심 문제를 직접 해결하는가. 엉뚱한 기능으로 새지 않았는가.
2. MVP 범위: 기능이 3~7개이고, 핵심 가치를 보여 주는 데 꼭 필요한 것만 남았는가. 인증, 결제, 관리자 화면처럼 시연에 필요 없는 기능이 끼어 있지 않은가.
3. 요구 대응: 아이디어 원문을 요구 단위로 직접 나눠 본 뒤 PRD의 Features와 대조하라. 원문의 요구가 빠졌으면 critical,
   원문에 없는 요구를 지어 넣었거나 뜻을 바꿨으면 major다. Out of scope가 원문의 요구를 빼 버렸으면 critical이다. 요구별 대조 결과를 summary에 짧게 남겨라.
4. 역할 분리: PRD는 무엇을 왜 만드는지만 다룬다. 기대 건수, 정확한 점수, 스택 이름처럼 spec이 정할 값을 확정해 적었으면 minor다.
"""

SPEC_RUBRIC = """\
1. 로컬 실행 가능성: 외부 유료 서비스, API 키, 별도 DB 서버 없이 install_cmd와 run_cmd만으로 한 대의 맥에서 실행되는가. 스택이 아이디어에 비해 과하지 않은가.
2. 기준의 검증 가능성: 모든 acceptance criterion이 자동 테스트나 HTTP 요청으로 참/거짓을 판정할 수 있게 구체적인가.
   기대 건수나 순서처럼 데이터에서 나오는 값은 context/ 자료로 직접 계산해 맞는지 확인하라. 틀린 기대값은 critical이다.
3. 명령의 정확성: install_cmd, test_cmd, run_cmd, smoke가 선택한 스택에서 실제로 동작할 명령인가. 서버라면 PORT 환경변수를 쓰고 smoke.url에 {port}가 있는가.
4. PRD 대응: features가 PRD.md의 Features와 같고, intent가 아이디어 원문의 요구를 빠짐없이 feature에 연결하는가. 연결된 criterion이 그 요구를 실제로 해결하지 못하면 critical이다.
5. PRD 결함: PRD.md 자체가 틀렸거나 서로 모순이면 location을 PRD.md로 issue에 남겨라. spec에서 바로잡을 수 있으면 spec 쪽 수정 방향을 fix에 적는다.
   spec에서 바로잡을 수 없는 PRD 결함은 기록만 하는 것이다. severity는 minor로 하고 pass와 score에 반영하지 않는다.
"""

BUILD_RUBRIC = """\
1. 기준 충족: spec.json의 acceptance criterion마다 구현이 있고, 실제로 앱을 띄워 확인했을 때 동작하는가. 기준별로 확인 결과를 issue 또는 summary에 남겨라.
2. 테스트: 각 기준을 검증하는 자동 테스트가 있고 test_cmd로 통과하는가. 테스트가 아무것도 검사하지 않는 형식뿐이지 않은가.
3. 사용 가능성: 첫 화면이나 첫 응답에서 무엇을 할 수 있는지 알 수 있는가. 빈 화면, 깨진 링크, 콘솔 에러가 없는가.
4. 결함: 명백한 버그, 입력 검증 누락으로 인한 500 에러, 비밀값 하드코딩, 주입 취약점이 없는가.
5. 실행 안내: app/README.md에 설치와 실행 방법이 정확히 적혀 있는가.
6. 디자인 (작업 폴더에 DESIGN.md가 있을 때만): CSS가 DESIGN.md의 색상, 글꼴, 간격 토큰과 레이아웃 규칙을 따르는가.
   흔한 카드 그리드로 되돌아갔으면 major다. 의외성 때문에 기능을 찾을 수 없거나 360px 폭에서 가로로 넘치면 major다.
"""
