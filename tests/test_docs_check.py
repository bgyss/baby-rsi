import json
import shutil
from pathlib import Path

from siro.docs_check import check_docs


def copy_docs_tree(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    shutil.copytree("docs", root / "docs")
    shutil.copy("README.md", root / "README.md")
    return root


def test_current_docs_contract_passes():
    result = check_docs(Path("."))
    assert result.ok, result.errors


def test_goal_prompt_without_manifest_entry_fails(tmp_path):
    root = copy_docs_tree(tmp_path)
    (root / "docs/goal_prompts/goal_99_new.md").write_text(
        "# Goal Prompt 99 - New\n\n## Self-improvement\n\nBounded.\n",
        encoding="utf-8",
    )

    result = check_docs(root)

    assert not result.ok
    assert any("goal_99_new.md: goal prompt is missing" in error for error in result.errors)


def test_goal_prompt_without_self_improvement_fails_with_path(tmp_path):
    root = copy_docs_tree(tmp_path)
    prompt = root / "docs/goal_prompts/goal_01_project_scaffold.md"
    prompt.write_text("# Goal Prompt 01 - Project scaffold\n\nNo section here.\n", encoding="utf-8")

    result = check_docs(root)

    assert not result.ok
    assert any(
        "docs/goal_prompts/goal_01_project_scaffold.md: missing required" in error
        for error in result.errors
    )


def test_readme_status_drift_fails_when_manifest_says_implemented(tmp_path):
    root = copy_docs_tree(tmp_path)
    readme = root / "README.md"
    text = readme.read_text(encoding="utf-8")
    old_heading = "### Cross-Tier Hardening (Goals 13-20)"
    drift_heading = (
        "### Cross-Tier Hardening (Goals 13-20) "
        "— specified, not yet implemented"
    )
    text = text.replace(
        old_heading,
        drift_heading,
    )
    readme.write_text(text, encoding="utf-8")

    result = check_docs(root)

    assert not result.ok
    assert any(
        "Goal 13 — Documentation consistency contract is listed as unimplemented" in error
        for error in result.errors
    )


def test_docs_privacy_check_catches_personal_paths_and_honors_allowlist(tmp_path):
    root = copy_docs_tree(tmp_path)
    doc = root / "docs/tmp_privacy_note.md"
    doc.write_text("Leak: /Users/example/.codex/work\n", encoding="utf-8")
    result = check_docs(root)
    assert not result.ok
    assert any("forbidden personal path pattern" in error for error in result.errors)

    doc.write_text(
        "<!-- docs-privacy-allow-start: intentional forbidden-path examples -->\n"
        "Example only: /Users/example/.codex/work\n"
        "<!-- docs-privacy-allow-end -->\n",
        encoding="utf-8",
    )
    result = check_docs(root)
    assert result.ok, result.errors


def test_manifest_prompt_path_must_exist(tmp_path):
    root = copy_docs_tree(tmp_path)
    manifest = root / "docs/goal_prompts/goals.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["goals"][0]["prompt_path"] = "docs/goal_prompts/missing.md"
    manifest.write_text(json.dumps(data), encoding="utf-8")

    result = check_docs(root)

    assert not result.ok
    assert any("manifest prompt_path does not exist" in error for error in result.errors)
