"""사용자가 넘긴 참고 자료 폴더를 실행 폴더의 context/로 복사한다."""

from __future__ import annotations

import shutil
from pathlib import Path

CONTEXT_DIRNAME = "context"
MAX_CONTEXT_BYTES = 5 * 1024 * 1024


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
    secrets = [v for v in secret_values if len(v) >= 8]
    for p in files:
        text = p.read_bytes().decode("utf-8", errors="ignore")
        if any(v in text for v in secrets):
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


def list_context(run_dir: Path) -> list[str]:
    """실행 폴더 기준 context/ 안의 파일 경로 목록. 자료가 없으면 빈 목록."""
    dst = run_dir / CONTEXT_DIRNAME
    if not dst.is_dir():
        return []
    return [str(p.relative_to(run_dir)) for p in _files(dst)]
