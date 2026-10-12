import http.server
import json
import os
import stat
import threading
import time
import urllib.parse

import pytest

from mvpgen.envfiles import app_env
from mvpgen.guards import check_command
from mvpgen.identity import GitHubOidcRefresher, detect_auth

FED = {
    "ANTHROPIC_FEDERATION_RULE_ID": "fdrl_x",
    "ANTHROPIC_ORGANIZATION_ID": "00000000-0000-0000-0000-000000000000",
    "ANTHROPIC_SERVICE_ACCOUNT_ID": "svac_x",
    "ANTHROPIC_IDENTITY_TOKEN_FILE": "/tmp/jwt",
}


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path / "anthropic"))


def test_federation_env_detected():
    auth, warnings = detect_auth({**FED, "ANTHROPIC_CONFIG_DIR": os.environ["ANTHROPIC_CONFIG_DIR"]})
    assert auth == "Workload Identity Federation (환경변수)" and warnings == []


def test_literal_identity_token_also_counts():
    env = {**FED, "ANTHROPIC_IDENTITY_TOKEN": "eyJ..."}
    del env["ANTHROPIC_IDENTITY_TOKEN_FILE"]
    assert detect_auth(env)[0].startswith("Workload Identity Federation")


def test_partial_federation_warns_and_fails():
    env = {k: v for k, v in FED.items() if k != "ANTHROPIC_SERVICE_ACCOUNT_ID"}
    auth, warnings = detect_auth(env)
    assert auth is None
    assert any("ANTHROPIC_SERVICE_ACCOUNT_ID" in w for w in warnings)


def test_api_key_shadows_federation_with_warning():
    auth, warnings = detect_auth({**FED, "ANTHROPIC_API_KEY": "sk-ant-x"})
    assert auth == "ANTHROPIC_API_KEY"
    assert any("unset" in w for w in warnings)


def test_empty_api_key_warns():
    _, warnings = detect_auth({**FED, "ANTHROPIC_API_KEY": ""})
    assert any("빈 문자열" in w for w in warnings)


def test_active_profile_detected(tmp_path):
    cfg = tmp_path / "anthropic" / "configs"
    cfg.mkdir(parents=True)
    (cfg / "default.json").write_text(json.dumps({"authentication": {"type": "oidc_federation"}}))
    assert detect_auth({})[0] == "Anthropic 활성 프로필 default"


def test_nothing_configured():
    assert detect_auth({})[0] is None


def test_app_env_strips_federation(monkeypatch):
    for k, v in {**FED, "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "gh"}.items():
        monkeypatch.setenv(k, v)
    env = app_env({"MY_KEY": "1"})
    assert not any(k in env for k in FED) and "ACTIONS_ID_TOKEN_REQUEST_TOKEN" not in env
    assert env["MY_KEY"] == "1"


def test_guard_blocks_identity_token_access(tmp_path):
    assert check_command("cat $ANTHROPIC_IDENTITY_TOKEN_FILE", tmp_path)
    assert check_command('curl -H "Authorization: Bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" x', tmp_path)


class FakeGitHub(http.server.BaseHTTPRequestHandler):
    counter = 0
    seen: list = []

    def do_GET(self):
        FakeGitHub.counter += 1
        q = urllib.parse.urlparse(self.path).query
        FakeGitHub.seen.append((self.headers.get("Authorization"), urllib.parse.parse_qs(q)))
        body = json.dumps({"value": f"jwt-{FakeGitHub.counter}"}).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def fake_github(monkeypatch):
    FakeGitHub.counter, FakeGitHub.seen = 0, []
    server = http.server.HTTPServer(("127.0.0.1", 0), FakeGitHub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("ACTIONS_ID_TOKEN_REQUEST_URL", f"http://127.0.0.1:{server.server_port}/token?api-version=2.0")
    monkeypatch.setenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "gh-request-token")
    yield
    server.shutdown()


def test_refresher_rotates_token_and_hides_request_credentials(tmp_path, fake_github):
    assert GitHubOidcRefresher.available()
    token_file = tmp_path / "jwt"
    r = GitHubOidcRefresher(token_file, interval=0.2)
    assert "ACTIONS_ID_TOKEN_REQUEST_TOKEN" not in os.environ
    assert "ACTIONS_ID_TOKEN_REQUEST_URL" not in os.environ

    r.start()
    try:
        assert token_file.read_text() == "jwt-1"
        assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
        deadline = time.time() + 5
        while r.refreshes < 3 and time.time() < deadline:
            time.sleep(0.05)
    finally:
        r.stop()
    assert r.refreshes >= 3
    assert token_file.read_text() == f"jwt-{FakeGitHub.counter}"
    auth_header, query = FakeGitHub.seen[0]
    assert auth_header == "Bearer gh-request-token"
    assert query["audience"] == ["https://api.anthropic.com"]
    assert query["api-version"] == ["2.0"]
