"""LLM 없이 생성된 앱을 설치, 테스트, 실행해 확인한다."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from mvpgen.envfiles import app_env
from mvpgen.spec import Smoke, Spec

TAIL_CHARS = 4000


@dataclass
class StepResult:
    name: str
    ok: bool
    returncode: int | None
    output_tail: str
    duration_s: float


@dataclass
class VerifyResult:
    steps: list[StepResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.steps) and all(s.ok for s in self.steps)

    @property
    def failed_step(self) -> StepResult | None:
        return next((s for s in self.steps if not s.ok), None)

    def report(self) -> str:
        lines = [f"- {s.name}: {'통과' if s.ok else '실패'} ({s.duration_s:.1f}s)" for s in self.steps]
        failed = self.failed_step
        if failed:
            lines.append(f"\n[{failed.name} 출력 끝부분]\n{failed.output_tail}")
        return "\n".join(lines)


def _tail(text: str) -> str:
    return text if len(text) <= TAIL_CHARS else "...(앞부분 생략)\n" + text[-TAIL_CHARS:]


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_step(name: str, cmd: str, cwd: Path, timeout: float, env: dict[str, str] | None = None) -> StepResult:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") + (e.stderr or "")
        if isinstance(out, bytes):
            out = out.decode(errors="replace")
        return StepResult(name, False, None, _tail(f"{out}\n{timeout:.0f}초 안에 끝나지 않았다"), time.monotonic() - start)
    output = proc.stdout + proc.stderr
    return StepResult(name, proc.returncode == 0, proc.returncode, _tail(output), time.monotonic() - start)


def _check_smoke_once(smoke: Smoke, port: int, cwd: Path, env: dict[str, str]) -> tuple[bool, str]:
    if smoke.url is not None:
        url = smoke.url.replace("{port}", str(port))
        try:
            r = httpx.get(url, timeout=5, follow_redirects=True)
        except httpx.HTTPError as e:
            return False, f"GET {url} 실패: {e!r}"
        if r.status_code >= 500:
            return False, f"GET {url} -> {r.status_code}"
        if smoke.expect not in r.text:
            return False, f"GET {url} -> {r.status_code}, 응답에 {smoke.expect!r}가 없다:\n{r.text[:1000]}"
        return True, f"GET {url} -> {r.status_code}"
    assert smoke.command is not None
    step = run_step("smoke", smoke.command.replace("{port}", str(port)), cwd, 30, env)
    if not step.ok:
        return False, step.output_tail
    if smoke.expect not in step.output_tail:
        return False, f"출력에 {smoke.expect!r}가 없다:\n{step.output_tail}"
    return True, "smoke 명령 통과"


def _stop(proc: subprocess.Popen) -> str:
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=10)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    try:
        out, _ = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        out = ""
    return out or ""


def run_and_smoke(spec: Spec, app_dir: Path, port: int, env: dict[str, str]) -> StepResult:
    """run_cmd를 백그라운드로 띄우고 smoke가 통과할 때까지 기다린 뒤 종료한다."""
    start = time.monotonic()
    proc = subprocess.Popen(
        spec.run_cmd,
        shell=True,
        cwd=app_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    last = "아직 확인하지 못함"
    ok = False
    try:
        deadline = start + spec.startup_timeout
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                last = f"앱 프로세스가 종료 코드 {proc.returncode}로 먼저 끝났다"
                break
            ok, last = _check_smoke_once(spec.smoke, port, app_dir, env)
            if ok:
                break
            time.sleep(1)
        else:
            last = f"{spec.startup_timeout}초 안에 smoke가 통과하지 못했다. 마지막 결과: {last}"
    finally:
        server_out = _stop(proc)
    detail = last if ok else f"{last}\n\n[앱 출력]\n{server_out}"
    return StepResult("run+smoke", ok, proc.returncode, _tail(detail), time.monotonic() - start)


def verify_app(
    app_dir: Path,
    spec: Spec,
    *,
    install_timeout: float = 900,
    test_timeout: float = 600,
    extra_env: dict[str, str] | None = None,
) -> VerifyResult:
    result = VerifyResult()
    if not app_dir.is_dir():
        result.steps.append(StepResult("app 디렉토리", False, None, f"{app_dir}가 없다", 0.0))
        return result

    port = free_port()
    env = {**app_env(extra_env or {}), "PORT": str(port), "CI": "1"}

    if spec.install_cmd:
        result.steps.append(run_step("install", spec.install_cmd, app_dir, install_timeout, env))
        if not result.steps[-1].ok:
            return result
    result.steps.append(run_step("test", spec.test_cmd, app_dir, test_timeout, env))
    if not result.steps[-1].ok:
        return result
    result.steps.append(run_and_smoke(spec, app_dir, port, env))
    return result
