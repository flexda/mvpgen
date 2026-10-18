"""VoltAgent/awesome-design-md의 DESIGN.md를 design-library/로 내려받는다.

실행: uv run python scripts/sync_design_library.py
gh CLI 로그인이 필요하다. 파이프라인은 실행 중에 네트워크를 쓰지 않고 이 폴더만 읽는다.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from pathlib import Path

REPO = "VoltAgent/awesome-design-md"
ROOT = Path(__file__).resolve().parent.parent / "design-library"


def gh(path: str) -> dict | list:
    out = subprocess.run(["gh", "api", path], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def blob(sha: str) -> bytes:
    return base64.b64decode(gh(f"repos/{REPO}/git/blobs/{sha}")["content"])  # type: ignore[index]


def main() -> None:
    commit = gh(f"repos/{REPO}/commits/main")["sha"]  # type: ignore[index]
    tree = gh(f"repos/{REPO}/git/trees/{commit}?recursive=1")["tree"]  # type: ignore[index]
    files = [t for t in tree if t["path"].startswith("design-md/") and t["path"].endswith("/DESIGN.md")]
    license_sha = next(t["sha"] for t in tree if t["path"] == "LICENSE")

    if ROOT.exists():
        shutil.rmtree(ROOT)
    for t in files:
        brand = t["path"].split("/")[1]
        dst = ROOT / brand / "DESIGN.md"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(blob(t["sha"]))
    (ROOT / "LICENSE").write_bytes(blob(license_sha))
    (ROOT / "SOURCE.md").write_text(
        f"# 출처\n\nhttps://github.com/{REPO} 의 `design-md/<brand>/DESIGN.md`를 그대로 복사했다.\n\n"
        f"- 커밋: {commit}\n- 파일 수: {len(files)}\n- 라이선스: 저장소 MIT (LICENSE). 브랜드 공식 자료라는 표시는 없다.\n"
        "- 갱신: `uv run python scripts/sync_design_library.py`\n",
        encoding="utf-8",
    )
    print(f"{len(files)}개 DESIGN.md -> {ROOT} (commit {commit[:7]})")


if __name__ == "__main__":
    main()
