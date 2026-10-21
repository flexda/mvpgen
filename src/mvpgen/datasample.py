"""Build 전에 오케스트레이터가 원천 API 샘플을 대신 받아 context/samples/에 둔다.

데이터 모드의 에이전트 세션에는 API 키를 주지 않는다. 에이전트는 이 샘플로 응답 형식을 보고 fixture를 만들고,
실제 호출은 페이지 제한이 걸린 자동 검사의 적재 단계에서만 일어난다.
"""

from __future__ import annotations

import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from mvpgen.context import CONTEXT_DIRNAME
from mvpgen.dataspec import DataSpec
from mvpgen.dbverify import mask

SAMPLES_DIRNAME = "samples"
MAX_SAMPLE_BYTES = 2_000_000
SAMPLE_TIMEOUT = 30

# (url, headers) -> (HTTP 상태, Content-Type, 본문). 테스트에서는 가짜로 바꾼다
Fetch = Callable[[str, dict[str, str]], tuple[int, str, bytes]]


def _ssl_context() -> ssl.SSLContext:
    # python.org 배포판 Python은 시스템 인증서를 쓰지 않아 검증에 실패할 수 있다. certifi가 있으면 그 묶음을 쓴다
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def http_fetch(url: str, headers: dict[str, str]) -> tuple[int, str, bytes]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=SAMPLE_TIMEOUT, context=_ssl_context()) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read(MAX_SAMPLE_BYTES + 1)
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read(MAX_SAMPLE_BYTES + 1)


def _ext(content_type: str, body: bytes) -> str:
    ct = content_type.lower()
    head = body.lstrip()[:1]
    if "json" in ct or head in (b"{", b"["):
        return "json"
    if "xml" in ct or head == b"<":
        return "xml"
    return "txt"


@dataclass
class SampleResult:
    ok: bool
    message: str
    calls: int = 0
    files: list[str] = field(default_factory=list)


def samples_dir(run_dir: Path) -> Path:
    return run_dir / CONTEXT_DIRNAME / SAMPLES_DIRNAME


def fetch_samples(spec: DataSpec, run_dir: Path, env: dict[str, str], fetch: Fetch = http_fetch) -> SampleResult:
    """spec.source.sample대로 페이지를 받아 저장한다. 이미 받은 샘플이 있으면 다시 부르지 않는다."""
    dest = samples_dir(run_dir)
    readme = dest / "README.md"
    if readme.exists():
        return SampleResult(True, "이전 실행에서 받은 샘플을 쓴다",
                            files=sorted(p.name for p in dest.glob("page-*")))

    sample = spec.source.sample
    key = ""
    if spec.source.key_env:
        key = env.get(spec.source.key_env, "")
        if not key:
            return SampleResult(False, f"{spec.source.key_env} 값이 없어 샘플을 받지 못했다")
    secrets = [s for s in (key, urllib.parse.quote(key, safe=""), urllib.parse.quote_plus(key)) if s]

    def fill(s: str, page: int) -> str:
        return s.replace("{key}", key).replace("{page}", str(page))

    dest.mkdir(parents=True, exist_ok=True)
    result = SampleResult(True, "")
    lines = ["# API 샘플", "", "mvpgen이 Build 전에 받아 둔 실제 응답이다. 키는 ***로 가렸다.", ""]
    for page in range(1, sample.pages + 1):
        params = {k: fill(v, page) for k, v in sample.params.items()}
        url = fill(sample.url, page)
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        headers = {k: fill(v, page) for k, v in sample.headers.items()}
        shown = mask(url, secrets)
        try:
            status, ctype, body = fetch(url, headers)
        except Exception as e:  # noqa: BLE001 - 네트워크 오류는 메시지로 돌려준다
            result.calls += 1
            return SampleResult(False, f"샘플 요청 실패 (page {page}): {mask(str(e), secrets)}", result.calls)
        result.calls += 1
        if len(body) > MAX_SAMPLE_BYTES:
            return SampleResult(False, f"page {page} 응답이 {MAX_SAMPLE_BYTES}바이트를 넘는다. 페이지 크기를 줄여라",
                                result.calls)
        text = mask(body.decode("utf-8", errors="replace"), secrets)
        name = f"page-{page}.{_ext(ctype, body)}"
        (dest / name).write_text(text, encoding="utf-8")
        result.files.append(name)
        lines.append(f"- {name}: HTTP {status}, {ctype or 'Content-Type 없음'}, {len(body)}바이트, 요청 `{shown}`")
        if status >= 400:
            # README.md는 성공했을 때만 쓴다. 없으면 다음 실행이 다시 받는다
            (dest / "ERROR.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
            return SampleResult(False, f"샘플 요청이 HTTP {status}로 실패했다 (page {page}). {name} 참고",
                                result.calls, result.files)
    (dest / "ERROR.md").unlink(missing_ok=True)
    readme.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result.message = f"샘플 {len(result.files)}개를 받았다 (API 호출 {result.calls}회)"
    return result
