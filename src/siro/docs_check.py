"""Documentation consistency and privacy checks (Goal 13)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_MANIFEST_PATH = Path("docs/goal_prompts/goals.json")
FORBIDDEN_PRIVACY_PATTERNS = ("/Users/", "/home/", ".codex", "/Applications", "/private/tmp")
VALID_STATUSES = {"implemented", "specified"}


@dataclass(frozen=True)
class DocsCheckResult:
    errors: tuple[str, ...]
    checked_goal_count: int
    checked_doc_count: int
    checked_privacy_file_count: int

    @property
    def ok(self) -> bool:
        return not self.errors


def check_docs(
    root: Path = Path("."), manifest_path: Path = DEFAULT_MANIFEST_PATH
) -> DocsCheckResult:
    root = root.resolve()
    manifest_file = _resolve(root, manifest_path)
    errors: list[str] = []

    try:
        manifest = _load_manifest(manifest_file)
    except ValueError as exc:
        return DocsCheckResult((str(exc),), 0, 0, 0)

    goals = manifest.get("goals")
    if not isinstance(goals, list):
        return DocsCheckResult(
            ("docs/goal_prompts/goals.json: top-level 'goals' must be a list",),
            0,
            0,
            0,
        )

    entries = [_normalize_goal_entry(goal, index) for index, goal in enumerate(goals, start=1)]
    entries_by_path: dict[str, dict[str, Any]] = {}
    entries_by_number: dict[int, dict[str, Any]] = {}
    for entry in entries:
        errors.extend(entry.pop("_errors"))
        prompt_path = entry.get("prompt_path")
        number = entry.get("number")
        if isinstance(prompt_path, str):
            if prompt_path in entries_by_path:
                errors.append(
                    f"{manifest_file.relative_to(root)}: duplicate prompt_path {prompt_path}"
                )
            entries_by_path[prompt_path] = entry
        if isinstance(number, int):
            if number in entries_by_number:
                errors.append(f"{manifest_file.relative_to(root)}: duplicate goal number {number}")
            entries_by_number[number] = entry

    prompt_files = sorted(root.glob("docs/goal_prompts/goal_*.md"))
    prompt_rel_paths = {_rel(path, root) for path in prompt_files}
    manifest_prompt_paths = set(entries_by_path)

    for path in sorted(prompt_rel_paths - manifest_prompt_paths):
        errors.append(f"{path}: goal prompt is missing from docs/goal_prompts/goals.json")
    for path in sorted(manifest_prompt_paths - prompt_rel_paths):
        errors.append(f"{path}: manifest prompt_path does not exist")

    for prompt in prompt_files:
        text = prompt.read_text(encoding="utf-8")
        if not re.search(r"^## Self-improvement\s*$", text, flags=re.MULTILINE):
            errors.append(f"{_rel(prompt, root)}: missing required '## Self-improvement' section")

    readme = root / "README.md"
    if readme.exists():
        readme_text = readme.read_text(encoding="utf-8")
        errors.extend(_check_readme_status(readme_text, entries_by_number))
        errors.extend(_check_readme_document_map(root, readme_text))
    else:
        errors.append("README.md: file is missing")

    privacy_files = _privacy_files(root)
    errors.extend(_check_privacy(root, privacy_files))

    return DocsCheckResult(
        errors=tuple(errors),
        checked_goal_count=len(entries),
        checked_doc_count=len(list(root.glob("docs/[0-9][0-9]_*.md"))),
        checked_privacy_file_count=len(privacy_files),
    )


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"{path}: manifest file is missing")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path}: manifest must be a JSON object")
    return data


def _normalize_goal_entry(goal: Any, index: int) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(goal, dict):
        return {"_errors": [f"goals[{index}]: entry must be an object"]}

    entry = dict(goal)
    prefix = f"goals[{index}]"
    required = ("number", "title", "status", "category", "prompt_path", "artifacts", "summary")
    for key in required:
        if key not in entry:
            errors.append(f"{prefix}: missing required field '{key}'")

    if not isinstance(entry.get("number"), int):
        errors.append(f"{prefix}: number must be an integer")
    if not isinstance(entry.get("title"), str) or not entry.get("title"):
        errors.append(f"{prefix}: title must be a non-empty string")
    if entry.get("status") not in VALID_STATUSES:
        errors.append(f"{prefix}: status must be one of {sorted(VALID_STATUSES)}")
    if not isinstance(entry.get("category"), str) or not entry.get("category"):
        errors.append(f"{prefix}: category must be a non-empty string")
    if not isinstance(entry.get("prompt_path"), str) or not entry.get("prompt_path"):
        errors.append(f"{prefix}: prompt_path must be a non-empty string")
    if not isinstance(entry.get("artifacts"), list) or not all(
        isinstance(item, str) and item for item in entry.get("artifacts", [])
    ):
        errors.append(f"{prefix}: artifacts must be a list of non-empty strings")
    if not isinstance(entry.get("summary"), str) or not entry.get("summary"):
        errors.append(f"{prefix}: summary must be a non-empty string")

    entry["_errors"] = errors
    return entry


def _check_readme_status(
    readme_text: str, entries_by_number: dict[int, dict[str, Any]]
) -> list[str]:
    errors: list[str] = []
    implemented_numbers = sorted(
        number for number, entry in entries_by_number.items() if entry["status"] == "implemented"
    )
    specified_numbers = sorted(
        number for number, entry in entries_by_number.items() if entry["status"] == "specified"
    )

    expected_summary = _status_summary(implemented_numbers, specified_numbers)
    if expected_summary not in _squash_ws(readme_text):
        errors.append(f"README.md: implementation status summary must include '{expected_summary}'")

    sections = _readme_goal_sections(readme_text)
    for number, entry in sorted(entries_by_number.items()):
        marker = f"Goal {number:02d} \u2014 {entry['title']}"
        if marker not in readme_text:
            errors.append(f"README.md: missing status entry for {marker}")
        section = sections.get(number, "")
        if entry["status"] == "implemented" and "specified, not yet implemented" in section:
            errors.append(
                f"README.md: {marker} is listed as unimplemented but manifest says implemented"
            )
        if entry["status"] == "specified" and "specified, not yet implemented" not in section:
            errors.append(
                f"README.md: {marker} is not listed under a specified/not-yet-implemented section"
            )
    return errors


def _status_summary(implemented: list[int], specified: list[int]) -> str:
    implemented_part = _range_text(implemented)
    specified_part = _range_text(specified)
    if specified:
        return (
            f"Goals {implemented_part} are implemented; Goals {specified_part} are "
            "specified, not yet implemented."
        )
    return f"Goals {implemented_part} are implemented."


def _range_text(numbers: list[int]) -> str:
    if not numbers:
        return "none"
    ranges: list[str] = []
    start = prev = numbers[0]
    for number in numbers[1:]:
        if number == prev + 1:
            prev = number
            continue
        ranges.append(_format_range(start, prev))
        start = prev = number
    ranges.append(_format_range(start, prev))
    return ", ".join(ranges)


def _format_range(start: int, end: int) -> str:
    return f"{start:02d}" if start == end else f"{start:02d}-{end:02d}"


def _readme_goal_sections(readme_text: str) -> dict[int, str]:
    sections: dict[int, str] = {}
    current_heading = ""
    for line in readme_text.splitlines():
        if line.startswith("### "):
            current_heading = line
            continue
        match = re.search(r"Goal ([0-9]{2}) \u2014", line)
        if match:
            sections[int(match.group(1))] = current_heading
    return sections


def _check_readme_document_map(root: Path, readme_text: str) -> list[str]:
    errors: list[str] = []
    for doc in sorted(root.glob("docs/[0-9][0-9]_*.md")):
        rel = _rel(doc, root)
        if f"`{rel}`" not in readme_text:
            errors.append(f"README.md: document map is missing `{rel}`")
    return errors


def _privacy_files(root: Path) -> list[Path]:
    files = list(root.glob("docs/**/*.md"))
    readme = root / "README.md"
    if readme.exists():
        files.append(readme)
    return sorted(files)


def _check_privacy(root: Path, files: list[Path]) -> list[str]:
    errors: list[str] = []
    for path in files:
        allow_block = False
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "docs-privacy-allow-start" in line:
                allow_block = True
                continue
            if "docs-privacy-allow-end" in line:
                allow_block = False
                continue
            if allow_block or "docs-privacy-allow" in line:
                continue
            for pattern in FORBIDDEN_PRIVACY_PATTERNS:
                if pattern in line:
                    errors.append(
                        f"{_rel(path, root)}:{line_no}: "
                        f"forbidden personal path pattern {pattern!r}"
                    )
    return errors


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _rel(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def _squash_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


__all__ = [
    "DEFAULT_MANIFEST_PATH",
    "DocsCheckResult",
    "FORBIDDEN_PRIVACY_PATTERNS",
    "check_docs",
]
