"""사용자가 넘긴 참고 자료 폴더와 요구 원문(brief)을 실행 폴더로 복사한다."""

from __future__ import annotations

import shutil
from pathlib import Path

CONTEXT_DIRNAME = "context"
MAX_CONTEXT_BYTES = 5 * 1024 * 1024
BRIEF_NAME = "brief.md"
MAX_BRIEF_BYTES = 200 * 1024


class ContextError(ValueError):
    pass


def _files(src: Path) -> list[Path]:
    # .DS_Store, .git 같은 숨김 항목은 자료가 아니므로 뺀다
    return sorted(
        p for p in src.rglob("*")
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(src).parts)
    )


def copy_context(src: Path, run_dir: Path, secret_values: list[str]) -> Path:
    """src를 run_dir/context로 복사한다. mvp.env의 비밀값이 자료에 들어 있으면 복사하지 않고 ContextError를 낸다."""
    if not src.is_dir():
        raise ContextError(f"{src}는 폴더가 아니다")
    files = _files(src)
    if not files:
        raise ContextError(f"{src}에 자료 파일이 없다")
    total = sum(p.stat().st_size for p in files)
    if total > MAX_CONTEXT_BYTES:
        raise ContextError(f"{src}가 너무 크다 ({total // 1024}KB, 최대 {MAX_CONTEXT_BYTES // 1024}KB)")
    for p in files:
        text = p.read_bytes().decode("utf-8", errors="ignore")
        if _has_secret(text, secret_values):
            # 어떤 키인지는 밝히지 않는다. 값이 로그에 남지 않게 파일 위치만 알린다
            raise ContextError(f"{p.relative_to(src)}에 mvp.env의 비밀값이 그대로 들어 있다. 값을 지우고 환경변수 이름만 남겨라")

    dst = run_dir / CONTEXT_DIRNAME
    if dst.exists():
        shutil.rmtree(dst)
    for p in files:
        target = dst / p.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
    return dst


def _has_secret(text: str, secret_values: list[str]) -> bool:
    return any(v in text for v in secret_values if len(v) >= 8)


def copy_brief(src: Path, run_dir: Path, secret_values: list[str]) -> Path:
    """인터뷰로 정리한 요구 원문을 run_dir/brief.md로 복사한다. 비밀값이 있거나 비었으면 ContextError."""
    if not src.is_file():
        raise ContextError(f"{src}는 파일이 아니다")
    if src.stat().st_size > MAX_BRIEF_BYTES:
        raise ContextError(f"{src}가 너무 크다 (최대 {MAX_BRIEF_BYTES // 1024}KB). 요구만 남기고 자료는 --context로 넘겨라")
    text = src.read_text(encoding="utf-8")
    if not brief_title(text):
        raise ContextError(f"{src}가 비어 있다")
    if _has_secret(text, secret_values):
        raise ContextError(f"{src}에 mvp.env의 비밀값이 그대로 들어 있다. 값을 지우고 환경변수 이름만 남겨라")
    dst = run_dir / BRIEF_NAME
    shutil.copy2(src, dst)
    return dst


def brief_title(text: str) -> str:
    """brief의 첫 줄(제목 기호를 뗀 것). 아이디어 한 줄을 따로 주지 않았을 때 아이디어로 쓴다."""
    for line in text.splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line
    return ""


def list_context(run_dir: Path) -> list[str]:
    """실행 폴더 기준 context/ 안의 파일 경로 목록. 자료가 없으면 빈 목록."""
    dst = run_dir / CONTEXT_DIRNAME
    if not dst.is_dir():
        return []
    return [str(p.relative_to(run_dir)) for p in _files(dst)]
