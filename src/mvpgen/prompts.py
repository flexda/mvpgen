"""단계별 시스템 프롬프트와 작업 프롬프트."""

from __future__ import annotations

import json

from mvpgen.spec import PRD_HEADINGS, Spec

SPEC_EXAMPLE = {
    "name": "quick-notes",
    "summary": "메모를 빠르게 적고 태그로 찾는 웹앱",
    "stack": "Python 3.13, FastAPI, SQLite, 서버 렌더링 HTML, pytest",
    "intent": [
        {"requirement": "메모를 빠르게 적는다", "feature_ids": ["F1"]},
        {"requirement": "태그로 메모를 찾는다", "feature_ids": ["F2"]},
    ],
    "features": [
        {"id": "F1", "title": "메모 작성", "description": "제목과 본문으로 메모를 만든다"},
        {"id": "F2", "title": "태그 검색", "description": "태그를 눌러 해당 메모만 본다"},
    ],
    "acceptance_criteria": [
        {"id": "AC1", "feature_id": "F1", "description": "POST /notes 후 GET /에 새 메모 제목이 보인다"},
        {"id": "AC2", "feature_id": "F2", "description": "GET /?tag=work는 work 태그 메모만 보여 준다"},
    ],
    "install_cmd": "uv sync",
    "test_cmd": "uv run pytest -q",
    "run_cmd": "uv run uvicorn app.main:app --host 127.0.0.1 --port $PORT",
    "smoke": {"url": "http://127.0.0.1:{port}/", "expect": "Quick Notes"},
    "startup_timeout": 60,
}

PLAN_SYSTEM = f"""\
너는 한 줄 아이디어를 하루 안에 만들 수 있는 MVP 기획으로 바꾸는 제품 엔지니어다.
현재 작업 폴더에 두 파일을 작성한다. 다른 파일은 만들지 않는다.

1. PRD.md: 다음 제목을 이 순서대로 정확히 포함한다: {", ".join(PRD_HEADINGS)}.
   문제, 대상 사용자와 대표 시나리오, 기능 목록, 이번 MVP에서 하지 않을 것을 구체적으로 쓴다.
2. spec.json: 아래 예시와 같은 키를 갖는 JSON.
{json.dumps(SPEC_EXAMPLE, ensure_ascii=False, indent=2)}

spec.json 작성 규칙:
- name은 앱 내용을 나타내는 영문 소문자와 하이픈 이름으로 짓는다 (아이디어가 한글이어도). 결과 폴더 이름에 쓰인다.
- intent에는 아이디어 원문이 요구한 것을 빠짐없이 하나씩 나눠 적고(원문 표현을 살린다), 각각을 해결하는 feature id를 연결한다.
  원문에 없는 요구는 intent에 넣지 않는다. 시연에 필요한 보조 기능은 intent 없이 features에만 둘 수 있다.

스택 선택 규칙:
- macOS 한 대에서 install_cmd와 run_cmd만으로 실행되어야 한다. 별도 DB 서버와 Docker는 쓰지 않는다.
- 외부 API는 아래 '준비된 환경변수'에 키가 있는 서비스만, 아이디어에 꼭 필요할 때 쓴다. 목록에 없는 키가 필요한 서비스는 쓰지 않는다.
- 저장이 필요하면 SQLite나 파일을 쓴다. 아이디어에 맞는 가장 단순한 스택을 고른다.
- Python을 쓰면 uv를 쓴다 (pip 금지). Node를 쓰면 npm을 쓴다.
- 서버형 앱은 PORT 환경변수로 포트를 받고 127.0.0.1에서 듣는다. smoke.url에는 {{port}}를 쓴다.
- CLI형 앱이면 smoke.command를 쓰고 smoke.url은 생략한다.
- 모든 명령은 app/ 디렉토리를 기준으로 실행된다고 가정한다.
- 기능은 3~7개. feature마다 자동으로 판정 가능한 acceptance criterion을 하나 이상 둔다.
"""

BUILD_SYSTEM = """\
너는 기획 문서를 받아 동작하는 MVP를 구현하는 시니어 엔지니어다.
현재 작업 폴더에 PRD.md와 spec.json이 있다. 코드는 모두 app/ 아래에 작성한다. PRD.md와 spec.json은 고치지 않는다.

작업 원칙:
- spec.json의 stack, install_cmd, test_cmd, run_cmd, smoke를 그대로 따른다. 명령이 그대로 동작하도록 프로젝트를 구성한다.
- acceptance criterion마다 이를 검증하는 자동 테스트를 작성한다.
- 서버는 PORT 환경변수를 읽고 127.0.0.1에서 듣는다. smoke.expect 문자열이 첫 응답에 나와야 한다.
- 끝내기 전에 app/에서 install_cmd와 test_cmd를 직접 실행해 통과를 확인한다.
- 서버를 직접 띄워 확인했다면 끝내기 전에 반드시 종료한다. 백그라운드 프로세스를 남기지 않는다.
- app/README.md에 설치와 실행 방법을 적는다. run_cmd가 $PORT를 쓰면 `PORT=8000 명령` 한 줄이 아니라 `export PORT=8000`을 먼저 적는다 (같은 줄 할당은 $PORT 펼침보다 늦다).
- Python 패키지는 uv로만 설치한다 (pip 금지).
- 외부 API 키는 환경변수 이름으로만 읽는다. 값을 코드, 설정 파일, 명령에 직접 쓰지 않는다. 필요한 이름은 app/.env.example에 값 없이 적는다.
- 외부 API를 부르는 코드의 자동 테스트는 응답을 mock 처리해 네트워크 없이 통과하게 한다.
- 작업을 마치면 자동 검사(install, test, 실행 + smoke)가 돈다. 실패하면 결과가 전달되니 고쳐서 다시 마친다.
"""

CRITIC_SYSTEM = """\
너는 MVP 결과물을 냉정하게 평가하는 독립 리뷰어다. 결과물을 만든 사람과 대화한 적이 없다.
파일을 읽고(필요하면 실행해) 루브릭으로 채점한 뒤, 지정된 경로에 review JSON 하나만 작성한다. 결과물 자체는 절대 고치지 않는다.

review JSON 형식:
{
  "pass": true 또는 false,
  "score": 0~100 정수,
  "summary": "한두 문장 총평",
  "issues": [
    {"severity": "critical|major|minor", "location": "파일 경로나 기준 id", "problem": "무엇이 문제인지", "fix": "어떻게 고칠지"}
  ]
}

채점 기준:
- critical: 핵심 기능이 동작하지 않거나 기준을 충족하지 못함. 하나라도 있으면 pass는 false.
- major: 사용자가 바로 알아챌 결함이나 루브릭 항목 미충족.
- minor: 다듬으면 좋은 점.
- 80점 이상이고 critical이 없을 때만 pass를 true로 한다.
- 추측으로 채점하지 말고, 확인한 근거를 problem에 적는다.
"""


def env_note(keys: list[str]) -> str:
    if not keys:
        return "\n\n# 준비된 환경변수\n없음. 외부 API 키가 필요한 서비스는 쓰지 않는다."
    return (
        "\n\n# 준비된 환경변수\n"
        + ", ".join(keys)
        + "\n실행 환경에 이 이름으로 값이 들어 있다. 값은 알려 주지 않으며 알아내려고 하지 않는다."
    )


def plan_prompt(idea: str, feedback: str | None) -> str:
    prompt = f"아이디어: {idea}\n\nPRD.md와 spec.json을 작성하라."
    if feedback:
        prompt += (
            "\n\n이전 버전이 리뷰를 통과하지 못했다. 기존 파일을 읽고 아래 지적을 모두 반영해 두 파일을 고쳐라.\n\n"
            + feedback
        )
    return prompt


def build_prompt(spec: Spec, feedback: str | None) -> str:
    prompt = (
        f"PRD.md와 spec.json을 읽고 '{spec.name}' MVP를 app/ 아래에 구현하라.\n"
        f"스택: {spec.stack}\n기능 {len(spec.features)}개, 완료 기준 {len(spec.acceptance_criteria)}개."
    )
    if feedback:
        prompt += (
            "\n\n이미 app/에 구현이 있다. 리뷰에서 아래 문제가 지적되었다. 모두 고치고, 관련 테스트를 보강하라.\n\n"
            + feedback
        )
    return prompt


def fix_prompt(report: str) -> str:
    return (
        "app/의 자동 검사가 실패했다. 원인을 찾아 고치고 install_cmd와 test_cmd로 직접 확인한 뒤 마쳐라.\n\n"
        + report
    )


def critic_prompt(stage: str, idea: str, rubric: str, review_path: str, port: int | None = None) -> str:
    target = (
        "PRD.md와 spec.json" if stage == "plan" else "spec.json의 기준에 비춘 app/ 구현"
    )
    prompt = (
        f"원래 아이디어: {idea}\n\n평가 대상: {target}\n\n루브릭:\n{rubric}\n"
        f"평가 결과를 {review_path}에 작성하라."
    )
    if port is not None:
        prompt += (
            f"\n\n앱을 직접 실행해 기준을 하나씩 확인하라. PORT={port}로 실행하고(app/에서 spec.json의 run_cmd), "
            "curl 등으로 확인한 뒤 서버를 반드시 종료하라."
        )
    return prompt
