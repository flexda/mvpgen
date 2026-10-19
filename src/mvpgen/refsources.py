"""레퍼런스 사이트 목록(design-sources.toml)을 읽고, 에이전트가 고른 URL을 검사해 원본 DESIGN.md를 내려받는다."""

from __future__ import annotations

import json
import re
import tomllib
import urllib.request
from dataclasses import dataclass
from pathlib import Path

MAX_DESIGN_BYTES = 300 * 1024
PICKS_NAME = "design-refs.json"
MIN_PICKS, MAX_PICKS = 3, 8
FETCH_TIMEOUT_S = 20
GITHUB_HOSTS = ("github.com", "raw.githubusercontent.com")
URL = re.compile(r"^https://(github\.com)/([^/]+/[^/]+)/blob/([^/]+)/(.+)$|^https://(raw\.githubusercontent\.com)/([^/]+/[^/]+)/([^/]+)/(.+)$")


class RefError(ValueError):
    pass


@dataclass(frozen=True)
class RefSource:
    name: str
    type: str  # web 또는 app
    repo: str
    ref: str
    path_prefix: str
    license: str
    note: str = ""

    @property
    def search_domains(self) -> tuple[str, ...]:
        # WebSearch는 호스트 단위로만 거를 수 있다. 저장소 단위 제한은 resolve()가 지킨다
        return GITHUB_HOSTS


@dataclass(frozen=True)
class Ref:
    source: RefSource
    name: str  # design-candidates/<name>.md 이름
    url: str  # 에이전트가 고른 URL
    raw_url: str

    @property
    def attribution(self) -> str:
        return f"{self.url} ({self.source.repo}, {self.source.license})"


def load_sources(path: Path) -> list[RefSource]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    sources = [RefSource(**s) for s in data.get("source", [])]
    bad = [s.name for s in sources if s.type not in ("web", "app")]
    if bad:
        raise RefError(f"{path.name}의 type은 web이나 app이어야 한다: {bad}")
    return sources


def web_domains(sources: list[RefSource]) -> list[str]:
    return sorted({d for s in sources for d in s.search_domains})


def resolve(url: str, sources: list[RefSource], kind: str) -> Ref:
    """목록에 있는 저장소의 path_prefix 아래 DESIGN.md를 가리키는 https URL만 받는다."""
    m = URL.match(url.strip())
    if not m:
        raise RefError(f"{url}: GitHub 파일 URL(https://github.com/<저장소>/blob/<ref>/<경로>)이 아니다")
    repo, ref, path = (m.group(2), m.group(3), m.group(4)) if m.group(1) else (m.group(6), m.group(7), m.group(8))
    path = path.split("?", 1)[0].split("#", 1)[0]
    source = next((s for s in sources if s.repo.lower() == repo.lower()), None)
    if source is None:
        raise RefError(f"{url}: 목록에 없는 저장소({repo})다")
    if source.type != kind:
        raise RefError(f"{url}: {source.name}은 {source.type}형 원천인데, 이 앱은 {kind}형이다")
    if not path.startswith(source.path_prefix) or not path.lower().endswith("/design.md") or ".." in path.split("/"):
        raise RefError(f"{url}: {source.repo}의 {source.path_prefix} 아래 DESIGN.md가 아니다")
    name = f"{source.name}-{path.removeprefix(source.path_prefix).rsplit('/', 1)[0].replace('/', '-')}".lower()
    raw = f"https://raw.githubusercontent.com/{source.repo}/{ref}/{path}"
    return Ref(source, re.sub(r"[^a-z0-9-]", "-", name), url.strip(), raw)


def fetch(raw_url: str) -> str:
    """원본을 받는다. https만, 크기 제한, 텍스트만."""
    if not raw_url.startswith("https://raw.githubusercontent.com/"):
        raise RefError(f"{raw_url}: 받을 수 없는 주소다")
    req = urllib.request.Request(raw_url, headers={"User-Agent": "mvpgen"})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_S) as resp:  # noqa: S310 (주소는 위에서 고정 호스트로 검사)
        body = resp.read(MAX_DESIGN_BYTES + 1)
    if len(body) > MAX_DESIGN_BYTES:
        raise RefError(f"{raw_url}: {MAX_DESIGN_BYTES // 1024}KB보다 크다")
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError as e:
        raise RefError(f"{raw_url}: 텍스트가 아니다") from e


def check_picks(path: Path, sources: list[RefSource]) -> list[str]:
    """원천 검색 세션의 결과(design-refs.json)를 검사한다. URL은 내려받지 않고 형식만 본다."""
    if not path.exists():
        return [f"{path.name}이 없다"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [f"{path.name}이 올바른 JSON이 아니다: {e}"]
    if not isinstance(data, dict) or data.get("type") not in ("web", "app"):
        return [f"{path.name}의 type은 web이나 app이어야 한다"]
    picks = data.get("picks")
    if not isinstance(picks, list) or not MIN_PICKS <= len(picks) <= MAX_PICKS:
        return [f"{path.name}의 picks는 {MIN_PICKS}~{MAX_PICKS}개여야 한다"]
    problems: list[str] = []
    names: list[str] = []
    for i, pick in enumerate(picks, 1):
        if not isinstance(pick, dict) or not str(pick.get("why", "")).strip():
            problems.append(f"picks {i}번에 why(고른 이유)가 없다")
            continue
        try:
            names.append(resolve(str(pick.get("url", "")), sources, data["type"]).name)
        except RefError as e:
            problems.append(f"picks {i}번: {e}")
    if len(set(names)) != len(names):
        problems.append("picks에 같은 DESIGN.md가 두 번 있다")
    return problems
