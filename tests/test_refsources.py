import json
from pathlib import Path

import pytest

from mvpgen.refsources import RefError, check_picks, fetch, load_sources, resolve, web_domains

SOURCES = load_sources(Path(__file__).resolve().parent.parent / "design-sources.toml")
IOS = "https://github.com/meliwat/awesome-ios-design-md/blob/main/design-md/dating/bumble/DESIGN.md"
WIRED = "https://github.com/VoltAgent/awesome-design-md/blob/main/design-md/wired/DESIGN.md"


def test_registry_has_web_and_app_sources_on_github():
    assert {s.type for s in SOURCES} == {"web", "app"}
    assert web_domains(SOURCES) == ["github.com", "raw.githubusercontent.com"]


def test_resolve_maps_blob_and_raw_urls():
    ref = resolve(IOS, SOURCES, "app")
    assert ref.name == "ios-apps-dating-bumble"
    assert ref.raw_url == "https://raw.githubusercontent.com/meliwat/awesome-ios-design-md/main/design-md/dating/bumble/DESIGN.md"
    assert "MIT" in ref.attribution and IOS in ref.attribution
    raw = "https://raw.githubusercontent.com/VoltAgent/awesome-design-md/main/design-md/wired/DESIGN.md"
    assert resolve(raw, SOURCES, "web").name == "voltagent-wired"


@pytest.mark.parametrize("url, kind, msg", [
    ("https://github.com/someone/fork/blob/main/design-md/wired/DESIGN.md", "web", "목록에 없는 저장소"),
    ("http://github.com/VoltAgent/awesome-design-md/blob/main/design-md/wired/DESIGN.md", "web", "GitHub 파일 URL"),
    ("https://github.com/VoltAgent/awesome-design-md/blob/main/README.md", "web", "아래 DESIGN.md가 아니다"),
    ("https://github.com/VoltAgent/awesome-design-md/blob/main/design-md/../x/DESIGN.md", "web", "아래 DESIGN.md가 아니다"),
    (WIRED, "app", "web형 원천인데"),
    ("https://designmd.app/en/library/x", "web", "GitHub 파일 URL"),
])
def test_resolve_rejects(url, kind, msg):
    with pytest.raises(RefError, match=msg):
        resolve(url, SOURCES, kind)


def test_fetch_only_reads_github_raw():
    with pytest.raises(RefError, match="받을 수 없는 주소"):
        fetch("https://example.com/DESIGN.md")


def test_check_picks(tmp_path):
    path = tmp_path / "design-refs.json"
    assert check_picks(path, SOURCES) == ["design-refs.json이 없다"]
    picks = [{"url": WIRED, "why": "잡지형"}, {"url": WIRED.replace("wired", "vogue"), "why": "에디토리얼"},
             {"url": WIRED.replace("wired", "nike"), "why": "의외"}]
    path.write_text(json.dumps({"type": "web", "picks": picks}))
    assert check_picks(path, SOURCES) == []
    path.write_text(json.dumps({"type": "web", "picks": picks[:2]}))
    assert "3~8개" in check_picks(path, SOURCES)[0]
    path.write_text(json.dumps({"type": "web", "picks": [*picks, {"url": IOS, "why": "앱"}, {"url": WIRED, "why": "중복"}]}))
    problems = check_picks(path, SOURCES)
    assert any("4번" in p and "app형" in p for p in problems) and any("두 번" in p for p in problems)


def test_fetch_verifies_tls_with_certifi(monkeypatch):
    """python.org 파이썬은 시스템 인증서가 없어 기본 검증이 실패했다(첫 실제 실행). certifi 인증서로 검증하되 검증은 끄지 않는다."""
    import ssl

    import certifi
    import urllib.request

    seen = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            return b"# design"

    def fake_urlopen(req, timeout, context):
        seen["context"] = context
        return Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert fetch("https://raw.githubusercontent.com/VoltAgent/awesome-design-md/main/design-md/wired/DESIGN.md") == "# design"
    assert seen["context"].verify_mode == ssl.CERT_REQUIRED and seen["context"].check_hostname
    assert certifi.where()
