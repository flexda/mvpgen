import pytest

from mvpgen import prompts
from mvpgen.context import ContextError, copy_context, list_context


def _src(tmp_path):
    src = tmp_path / "docs"
    (src / "sub").mkdir(parents=True)
    (src / "api.md").write_text("서비스키: 환경변수 `MMCA_SERVICE_KEY`")
    (src / "sub" / "data.csv").write_text("title,start\nA,2026-10-01\n")
    (src / ".DS_Store").write_bytes(b"\x00")
    return src


def test_copy_context_skips_hidden_files(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    dst = copy_context(_src(tmp_path), run_dir, [])
    assert dst == run_dir / "context"
    assert list_context(run_dir) == ["context/api.md", "context/sub/data.csv"]


def test_copy_context_refuses_secret_values(tmp_path):
    src = _src(tmp_path)
    (src / "api.md").write_text("서비스키: 8bd0aaaa-1111-2222-3333-444455556666")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    with pytest.raises(ContextError, match="api.md") as e:
        copy_context(src, run_dir, ["8bd0aaaa-1111-2222-3333-444455556666"])
    assert "8bd0aaaa" not in str(e.value)
    assert not (run_dir / "context").exists()


def test_copy_context_rejects_missing_dir(tmp_path):
    with pytest.raises(ContextError):
        copy_context(tmp_path / "none", tmp_path, [])


def test_prompts_mention_context_only_when_present():
    files = ["context/api.md"]
    assert "context/api.md" in prompts.plan_prompt("아이디어", None, files)
    assert "크롤링하지 않" in prompts.plan_prompt("아이디어", None, files)
    assert "context/" not in prompts.plan_prompt("아이디어", None, [])
    assert "context/" in prompts.critic_prompt("plan", "아이디어", "루브릭", "reviews/plan-r1.json", has_context=True)
    assert "context/" not in prompts.critic_prompt("plan", "아이디어", "루브릭", "reviews/plan-r1.json")
