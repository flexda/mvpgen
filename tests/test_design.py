import json

import pytest

from mvpgen.design import (DESIGN_HEADINGS, check_design, check_directions, choose_direction, copy_candidates,
                           list_library, pick_candidates)

CANDIDATES = ["airbnb", "nintendo-2001", "spacex"]


def make_library(root, brands):
    for b in brands:
        (root / b).mkdir(parents=True)
        (root / b / "DESIGN.md").write_text(f"# {b}")
    return root


def good_concepts(**over):
    data = {
        "directions": [
            {"id": "A", "kind": "baseline", "sources": ["airbnb"], "metaphor": "m", "first_screen": "f", "risks": "r"},
            {"id": "B", "kind": "unexpected", "sources": ["nintendo-2001"], "metaphor": "m", "first_screen": "f", "risks": "r"},
            {"id": "C", "kind": "unexpected", "sources": ["spacex", "airbnb"], "metaphor": "m", "first_screen": "f", "risks": "r"},
        ],
        "chosen": "B",
        "reason": "카트리지 은유가 전시 고르기와 맞는다",
    }
    data.update(over)
    return data


def good_design_md():
    body = "\n\n".join(f"{h}\n" + "내용 " * 120 for h in DESIGN_HEADINGS)
    return '---\nname: x\ncolors:\n  ink: "#111111"\n---\n\n' + body


def write_run(tmp_path, concepts, design_md):
    (tmp_path / "concepts.json").write_text(json.dumps(concepts, ensure_ascii=False))
    (tmp_path / "DESIGN.md").write_text(design_md)


def test_pick_candidates_is_reproducible_and_bounded(tmp_path):
    lib = make_library(tmp_path / "lib", [f"b{i:02d}" for i in range(20)])
    first = pick_candidates(lib, 8, seed=42)
    assert first == pick_candidates(lib, 8, seed=42)
    assert len(first) == 8 and set(first) <= set(list_library(lib))
    assert pick_candidates(lib, 8, seed=43) != first
    assert len(pick_candidates(lib, 50, seed=1)) == 20


def test_copy_candidates_flattens_into_run_dir(tmp_path):
    lib = make_library(tmp_path / "lib", CANDIDATES)
    run = tmp_path / "run"
    run.mkdir()
    paths = copy_candidates(lib, ["spacex"], run)
    assert paths == ["design-candidates/spacex.md"]
    assert (run / "design-candidates" / "spacex.md").read_text() == "# spacex"


def test_check_design_passes(tmp_path):
    write_run(tmp_path, good_concepts(), good_design_md())
    assert check_design(tmp_path, CANDIDATES) == []


def test_check_design_accepts_baseline_choice(tmp_path):
    # 사람이 고르므로 기준안도 된다
    write_run(tmp_path, good_concepts(chosen="A"), good_design_md())
    assert check_design(tmp_path, CANDIDATES) == []


def test_check_directions_does_not_need_choice(tmp_path):
    concepts = good_concepts()
    del concepts["chosen"], concepts["reason"]
    write_run(tmp_path, concepts, "")
    assert check_directions(tmp_path / "concepts.json", CANDIDATES) == []
    assert any("chosen" in p for p in check_design(tmp_path, CANDIDATES))


def test_check_directions_rejects_duplicate_ids(tmp_path):
    concepts = good_concepts()
    concepts["directions"][2]["id"] = "B"
    write_run(tmp_path, concepts, "")
    assert any("서로 달라야" in p for p in check_directions(tmp_path / "concepts.json", CANDIDATES))


def test_choose_direction_records_human_choice(tmp_path):
    write_run(tmp_path, {"directions": good_concepts()["directions"]}, "")
    path = tmp_path / "concepts.json"
    assert choose_direction(path, "A", "무난한 게 낫다")["kind"] == "baseline"
    data = json.loads(path.read_text())
    assert (data["chosen"], data["reason"], data["chosen_by"]) == ("A", "무난한 게 낫다", "human")
    with pytest.raises(ValueError, match="가능한 값: A, B, C"):
        choose_direction(path, "Z", None)


def test_check_design_rejects_source_outside_candidates(tmp_path):
    concepts = good_concepts()
    concepts["directions"][1]["sources"] = ["ferrari"]
    write_run(tmp_path, concepts, good_design_md())
    assert any("ferrari" in p for p in check_design(tmp_path, CANDIDATES))


def test_check_design_requires_one_baseline_two_unexpected(tmp_path):
    concepts = good_concepts()
    concepts["directions"][0]["kind"] = "unexpected"
    write_run(tmp_path, concepts, good_design_md())
    assert any("baseline 1개" in p for p in check_design(tmp_path, CANDIDATES))


def test_check_design_md_needs_frontmatter_and_headings(tmp_path):
    write_run(tmp_path, good_concepts(), good_design_md().split("---\n\n", 1)[1].replace("## Layout", "## Grid"))
    problems = check_design(tmp_path, CANDIDATES)
    assert any("프런트매터" in p for p in problems)
    assert any("## Layout" in p for p in problems)


def test_check_design_missing_files(tmp_path):
    problems = check_design(tmp_path, CANDIDATES)
    assert "concepts.json이 없다" in problems and "DESIGN.md가 없다" in problems
