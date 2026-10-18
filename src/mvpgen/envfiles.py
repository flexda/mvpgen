"""secrets/ 폴더의 KEY=VALUE 파일을 읽는다.

- claude.env: mvpgen 자신이 Claude를 호출할 때 쓰는 인증 정보(API 키, 구독 토큰 또는 페더레이션 변수). 프로세스 환경변수로 올린다.
- mvp.env: 생성되는 MVP가 쓸 외부 API 키. 이름만 프롬프트에 알리고, 값은 Build 세션과 검증 실행의 환경변수로만 넘긴다.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

CLAUDE_FILE = "claude.env"
MVP_FILE = "mvp.env"
CLAUDE_CRED_KEYS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    # Workload Identity Federation과 GitHub OIDC 발급 권한도 생성된 앱에는 넘기지 않는다
    "ANTHROPIC_FEDERATION_RULE_ID",
    "ANTHROPIC_ORGANIZATION_ID",
    "ANTHROPIC_SERVICE_ACCOUNT_ID",
    "ANTHROPIC_WORKSPACE_ID",
    "ANTHROPIC_IDENTITY_TOKEN_FILE",
    "ANTHROPIC_IDENTITY_TOKEN",
    "ANTHROPIC_PROFILE",
    "ANTHROPIC_CONFIG_DIR",
    "ACTIONS_ID_TOKEN_REQUEST_URL",
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
)

_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def parse_env_file(path: Path) -> dict[str, str]:
    """주석(#)과 빈 줄을 건너뛰고, 값이 빈 항목은 버린다. 값을 감싼 따옴표는 벗긴다."""
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        m = _LINE.match(raw)
        if not m:
            continue
        key, value = m.group(1), m.group(2)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if value:
            values[key] = value
    return values


def load_claude_env(secrets_dir: Path) -> list[str]:
    """claude.env 값을 os.environ에 넣는다. 이미 셸에 설정된 값은 덮어쓰지 않는다. 적용한 키 이름을 돌려준다."""
    applied = []
    for key, value in parse_env_file(secrets_dir / CLAUDE_FILE).items():
        if not os.environ.get(key):
            os.environ[key] = value
            applied.append(key)
    return applied


def load_mvp_env(secrets_dir: Path) -> dict[str, str]:
    return parse_env_file(secrets_dir / MVP_FILE)


def app_env(extra: dict[str, str]) -> dict[str, str]:
    """생성된 앱을 실행할 환경. mvpgen의 Claude 인증 정보는 빼고 mvp.env 값을 더한다."""
    env = {k: v for k, v in os.environ.items() if k not in CLAUDE_CRED_KEYS}
    env.update(extra)
    return env
