from mvpgen.research import RESEARCH_HEADINGS, check_research


def test_check_research(tmp_path):
    path = tmp_path / "a.md"
    assert check_research(path) == ["research/a.md이 없다"]
    path.write_text("## 확인한 것\n짧다")
    problems = check_research(path)
    assert any("## 위험" in p for p in problems) and any("너무 짧다" in p for p in problems)
    path.write_text("\n\n".join(f"{h}\n" + "근거 " * 60 for h in RESEARCH_HEADINGS))
    assert check_research(path) == []
