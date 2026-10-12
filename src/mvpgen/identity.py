"""Workload Identity Federation 지원.

- detect_auth(): Claude 인증 수단이 준비되었는지 판정한다 (API 키, 클라우드 제공자, 페더레이션 변수, 프로필).
- GitHubOidcRefresher: GitHub Actions에서 OIDC 토큰을 주기적으로 받아 ANTHROPIC_IDENTITY_TOKEN_FILE에 쓴다.
  GitHub 토큰은 약 5분 뒤 만료되고 jti가 있어 한 번만 교환할 수 있으므로, 교환 때마다 새 토큰이 파일에 있어야 한다.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.parse
import urllib.request
from pathlib import Path

FEDERATION_REQUIRED = ("ANTHROPIC_FEDERATION_RULE_ID", "ANTHROPIC_ORGANIZATION_ID", "ANTHROPIC_SERVICE_ACCOUNT_ID")
FEDERATION_VARS = FEDERATION_REQUIRED + (
    "ANTHROPIC_WORKSPACE_ID",
    "ANTHROPIC_IDENTITY_TOKEN_FILE",
    "ANTHROPIC_IDENTITY_TOKEN",
    "ANTHROPIC_PROFILE",
    "ANTHROPIC_CONFIG_DIR",
)
CLOUD_PROVIDER_VARS = (
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDE_CODE_USE_ANTHROPIC_AWS",
)
GHA_REQUEST_VARS = ("ACTIONS_ID_TOKEN_REQUEST_URL", "ACTIONS_ID_TOKEN_REQUEST_TOKEN")
DEFAULT_AUDIENCE = "https://api.anthropic.com"


def anthropic_config_dir() -> Path:
    if os.environ.get("ANTHROPIC_CONFIG_DIR"):
        return Path(os.environ["ANTHROPIC_CONFIG_DIR"]).expanduser()
    return Path.home() / ".config" / "anthropic"


def _active_profile() -> str | None:
    cfg = anthropic_config_dir()
    active = cfg / "active_config"
    name = active.read_text(encoding="utf-8").strip() if active.exists() else "default"
    return name if (cfg / "configs" / f"{name}.json").exists() else None


def detect_auth(env: dict[str, str] | None = None) -> tuple[str | None, list[str]]:
    """(사용될 인증 수단 설명 또는 None, 경고 목록)을 돌려준다.

    순서는 Claude Code 인증 문서의 우선순위를 따른다. 빈 문자열 변수도 자리를 차지하므로 경고한다.
    """
    env = dict(os.environ) if env is None else env
    warnings = [
        f"{k}가 빈 문자열로 설정되어 있다. 빈 값도 우선순위를 차지하니 unset하라"
        for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
        if k in env and not env[k]
    ]
    federation_ready = all(env.get(k) for k in FEDERATION_REQUIRED) and bool(
        env.get("ANTHROPIC_IDENTITY_TOKEN_FILE") or env.get("ANTHROPIC_IDENTITY_TOKEN")
    )
    key_set = bool(env.get("ANTHROPIC_API_KEY") or env.get("ANTHROPIC_AUTH_TOKEN"))
    if key_set and (federation_ready or env.get("ANTHROPIC_PROFILE")):
        warnings.append("API 키가 설정되어 있어 페더레이션 대신 키가 쓰인다. 페더레이션을 쓰려면 ANTHROPIC_API_KEY를 unset하라")

    if any(env.get(k) for k in CLOUD_PROVIDER_VARS):
        return "클라우드 제공자", warnings
    if env.get("ANTHROPIC_AUTH_TOKEN"):
        return "ANTHROPIC_AUTH_TOKEN", warnings
    if env.get("ANTHROPIC_API_KEY"):
        return "ANTHROPIC_API_KEY", warnings
    if env.get("ANTHROPIC_PROFILE"):
        return f"Anthropic 프로필 {env['ANTHROPIC_PROFILE']}", warnings
    if federation_ready:
        return "Workload Identity Federation (환경변수)", warnings
    if any(env.get(k) for k in FEDERATION_REQUIRED):
        missing = [k for k in FEDERATION_REQUIRED if not env.get(k)]
        if not (env.get("ANTHROPIC_IDENTITY_TOKEN_FILE") or env.get("ANTHROPIC_IDENTITY_TOKEN")):
            missing.append("ANTHROPIC_IDENTITY_TOKEN_FILE 또는 ANTHROPIC_IDENTITY_TOKEN")
        warnings.append(f"페더레이션 변수가 일부만 설정되었다. 빠진 것: {', '.join(missing)}")
    profile = _active_profile()
    if profile:
        return f"Anthropic 활성 프로필 {profile}", warnings
    return None, warnings


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


class GitHubOidcRefresher:
    """GitHub Actions 러너에서 OIDC 토큰을 interval초마다 새로 받아 파일에 쓴다.

    생성 시 ACTIONS_ID_TOKEN_REQUEST_* 값을 메모리로 옮기고 os.environ에서 지운다.
    그래야 에이전트의 Bash나 생성된 앱이 GitHub 토큰을 직접 발급받을 수 없다.
    """

    def __init__(self, token_file: Path, audience: str = DEFAULT_AUDIENCE, interval: float = 60.0) -> None:
        self._url = os.environ.pop("ACTIONS_ID_TOKEN_REQUEST_URL")
        self._bearer = os.environ.pop("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
        self.token_file = token_file
        self.audience = audience
        self.interval = interval
        self.refreshes = 0
        self.last_error: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @staticmethod
    def available() -> bool:
        return all(os.environ.get(k) for k in GHA_REQUEST_VARS)

    def fetch(self) -> None:
        sep = "&" if "?" in self._url else "?"
        url = f"{self._url}{sep}audience={urllib.parse.quote(self.audience, safe='')}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self._bearer}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            token = json.load(resp)["value"]
        _write_atomic(self.token_file, token)
        self.refreshes += 1

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.fetch()
                self.last_error = None
            except Exception as e:  # 다음 주기에 다시 시도한다. 기존 파일은 그대로 둔다.
                self.last_error = repr(e)
                print(f"[oidc] 토큰 갱신 실패, 다음 주기에 재시도: {e!r}", flush=True)

    def start(self) -> None:
        self.fetch()
        self._thread = threading.Thread(target=self._loop, name="gha-oidc-refresher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
