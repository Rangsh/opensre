"""Registry-wide contract for SKILL.md attachment and the 2400-char budget.

Inventory is derived from the source tree (every ``SKILL.md`` whose frontmatter
declares ``tools:``), not a hand-written name list, so a new skill is covered
automatically. Existing over-budget skills are listed on a shrink-only
allowlist — new overruns fail; a rewritten skill that fits must drop its entry.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import yaml

from config.constants.paths import REPO_ROOT
from core.tool.contracts import RegisteredTool
from core.tool_framework import format_tool_skill_guidance, load_tool_skill_guidance
from tools.registry import clear_tool_registry_cache, get_registered_tools
from tools.registry_skill_guidance import (
    _MAX_TOOL_SKILL_GUIDANCE_CHARS,
    _skill_guidance_files,
    _truncate_skill_guidance,
    apply_skill_guidance,
)

# Pre-existing tools whose joined (pre-truncation) guidance already exceeds the
# registry cap. Shrink-only: a new over-budget tool fails; a tool that drops
# under the cap must be removed here. Listed in the #5501 PR as the rewrite backlog.
_OVER_BUDGET_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "call_posthog_tool",
        "execute_python_code",
        "execute_yc_operation",
        "find_yc_api",
        "list_posthog_tools",
    }
)

_SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "tests",
        "build",
        "dist",
    }
)


def _skill_inventory_path_is_skipped(path: Path, *, repo_root: Path = REPO_ROOT) -> bool:
    """Skip generated trees and test dirs, using parts relative to ``repo_root``.

    Absolute ``path.parts`` would hide the whole checkout if an ancestor is
    named ``tests`` or ``.venv``. PyInstaller ``build/`` and ``dist/`` copies
    must not enter the source inventory.
    """

    try:
        relative = path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return True
    return any(part in _SKIP_DIR_NAMES for part in relative.parts)


def _iter_tree_skill_files() -> tuple[Path, ...]:
    """Return every repo ``SKILL.md`` whose frontmatter declares ``tools:``."""

    paths: list[Path] = []
    for path in REPO_ROOT.rglob("SKILL.md"):
        if _skill_inventory_path_is_skipped(path):
            continue
        if _frontmatter_declares_tools(path):
            paths.append(path)
    return tuple(sorted(paths))


def _frontmatter_declares_tools(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return False
    end = text.find("\n---", 3)
    if end == -1:
        return False
    loaded = yaml.safe_load(text[4:end]) or {}
    return isinstance(loaded, dict) and "tools" in loaded


def _registered_tools_by_name() -> dict[str, RegisteredTool]:
    clear_tool_registry_cache()
    return {tool.name: tool for tool in get_registered_tools()}


def _tool(name: str) -> RegisteredTool:
    def _run(**_kwargs: Any) -> dict[str, Any]:
        return {"ok": True}

    return RegisteredTool(
        name=name,
        description=f"{name} tool.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        source="knowledge",
        run=cast(Callable[..., Any], _run),
    )


def _write_skill(path: Path, frontmatter: str, body: str = "Use this workflow.") -> None:
    path.write_text(f"---\n{frontmatter}\n---\n\n{body}\n", encoding="utf-8")


def test_skill_inventory_is_derived_from_the_tree_not_a_hand_written_list() -> None:
    tree = _iter_tree_skill_files()
    assert tree, "expected at least one SKILL.md with a tools: frontmatter key"
    registered = tuple(path.resolve() for path in _skill_guidance_files())
    tree_resolved = tuple(path.resolve() for path in tree)
    unregistered = [path for path in tree_resolved if path not in registered]
    stale = [path for path in registered if path not in tree_resolved]
    assert unregistered == [], (
        "SKILL.md files declare tools: but are not loaded by "
        "_skill_guidance_files(); add them or they attach to nothing:\n"
        + "\n".join(f"  - {path.relative_to(REPO_ROOT)}" for path in unregistered)
    )
    assert stale == [], "registered skill paths are missing from the tree inventory:\n" + "\n".join(
        f"  - {path.relative_to(REPO_ROOT)}" for path in stale
    )


def test_each_tree_skill_attaches_to_exactly_its_target_tools() -> None:
    tools_by_name = _registered_tools_by_name()
    known = frozenset(tools_by_name)
    for path in _iter_tree_skill_files():
        result = load_tool_skill_guidance(path, known_tool_names=known)
        assert result.skill is not None, (
            f"{path.relative_to(REPO_ROOT)} declares tools: but failed to load: "
            f"{[d.message for d in result.diagnostics]}"
        )
        skill = result.skill
        marker = f'<skill name="{skill.name}"'
        rel = path.relative_to(REPO_ROOT)
        targets = [name for name in skill.tool_names if name in tools_by_name]
        if skill.disable_model_invocation:
            attached = [
                name
                for name, tool in tools_by_name.items()
                if marker in tool.skill_guidance or marker in tool.description
            ]
            assert attached == [], (
                f"{rel} ({skill.name}) has disable-model-invocation but attached to {attached}"
            )
            continue
        missing = [
            name
            for name in targets
            if marker not in tools_by_name[name].skill_guidance
            or marker not in tools_by_name[name].description
        ]
        leaked = [
            name
            for name, tool in tools_by_name.items()
            if name not in skill.tool_names and marker in tool.skill_guidance
        ]
        assert missing == [], f"{rel} ({skill.name}) should attach to {missing} but did not"
        assert leaked == [], f"{rel} ({skill.name}) leaked onto {leaked}"


def test_tree_skills_do_not_name_unknown_tools() -> None:
    """A ``tools:`` target that names no registered tool fails this contract.

    The loader itself warns (``unknown_tool``) and still loads the skill; this
    test is what turns that silent miss into a red suite.
    """

    known = frozenset(tool.name for tool in _registered_tools_by_name().values())
    offenders: list[str] = []
    for path in _iter_tree_skill_files():
        result = load_tool_skill_guidance(path, known_tool_names=known)
        unknown = [d for d in result.diagnostics if d.code == "unknown_tool"]
        if unknown:
            rel = path.relative_to(REPO_ROOT)
            messages = "; ".join(d.message for d in unknown)
            offenders.append(f"{rel}: {messages}")
    assert offenders == [], "SKILL.md tools: target unknown tools:\n" + "\n".join(
        f"  - {item}" for item in offenders
    )


def test_over_budget_tools_are_listed_and_the_allowlist_only_shrinks() -> None:
    """Ratchet the joined per-tool payload, not each skill in isolation.

    Two sub-budget skills targeting one tool can still overrun once joined;
    disabled skills never reach the model and must not count.
    """

    tools_by_name = _registered_tools_by_name()
    known = frozenset(tools_by_name)
    guidance_by_tool: dict[str, list[str]] = {}
    for path in _iter_tree_skill_files():
        result = load_tool_skill_guidance(path, known_tool_names=known)
        skill = result.skill
        if skill is None or skill.disable_model_invocation:
            continue
        formatted = format_tool_skill_guidance(skill)
        for tool_name in skill.tool_names:
            if tool_name not in tools_by_name:
                continue
            guidance_by_tool.setdefault(tool_name, []).append(formatted)

    over_budget: dict[str, int] = {}
    for name, parts in guidance_by_tool.items():
        length = len("\n\n".join(parts))
        if length > _MAX_TOOL_SKILL_GUIDANCE_CHARS:
            over_budget[name] = length

    names = frozenset(over_budget)
    extra = names - _OVER_BUDGET_TOOL_NAMES
    stale = _OVER_BUDGET_TOOL_NAMES - names
    listing = ", ".join(f"{name} ({over_budget[name]} chars)" for name in sorted(over_budget))
    assert extra == frozenset(), (
        "new tool(s) over the "
        f"{_MAX_TOOL_SKILL_GUIDANCE_CHARS}-character joined-guidance budget: "
        f"{sorted(extra)}. Shorten the SKILL.md files that attach to them "
        f"(rewrites of existing over-budget files are a separate backlog: {listing})"
    )
    assert stale == frozenset(), (
        "tool(s) dropped under the joined-guidance budget; remove them from "
        f"_OVER_BUDGET_TOOL_NAMES: {sorted(stale)}"
    )


def test_apply_skill_guidance_warns_with_the_over_budget_list(
    caplog: Any,
) -> None:
    clear_tool_registry_cache()
    with caplog.at_level(logging.WARNING, logger="tools.registry_skill_guidance"):
        get_registered_tools()
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "over the 2400-character budget" in joined
    for name in sorted(_OVER_BUDGET_TOOL_NAMES):
        assert name in joined, name


def test_attached_guidance_stays_within_the_budget() -> None:
    for tool in _registered_tools_by_name().values():
        guidance = tool.skill_guidance
        if not guidance:
            continue
        assert len(guidance) <= _MAX_TOOL_SKILL_GUIDANCE_CHARS, tool.name
        if guidance.endswith("..."):
            stem = guidance[:-3]
            assert stem == stem.rstrip(), tool.name


def test_truncate_skill_guidance_is_a_no_op_when_under_the_cap() -> None:
    text = "short guidance"
    assert _truncate_skill_guidance(text) == text


def test_truncate_skill_guidance_appends_ellipsis_at_the_cap() -> None:
    text = "a" * (_MAX_TOOL_SKILL_GUIDANCE_CHARS + 50)
    truncated = _truncate_skill_guidance(text)
    assert truncated.endswith("...")
    assert len(truncated) <= _MAX_TOOL_SKILL_GUIDANCE_CHARS


def test_truncate_skill_guidance_does_not_split_a_word_when_a_boundary_exists() -> None:
    prefix = "word " * 500
    text = prefix + "complete_token_that_would_be_split"
    assert len(text) > _MAX_TOOL_SKILL_GUIDANCE_CHARS
    truncated = _truncate_skill_guidance(text)
    assert truncated.endswith("...")
    assert "complete_token_that_would_be_split" not in truncated
    assert not truncated[:-3].endswith("complete")


def test_truncate_skill_guidance_does_not_split_before_an_underscore() -> None:
    budget = _MAX_TOOL_SKILL_GUIDANCE_CHARS - 3
    text = "x" * (budget - 4) + " foo_bar_rest"
    assert len(text) > _MAX_TOOL_SKILL_GUIDANCE_CHARS
    truncated = _truncate_skill_guidance(text)
    assert truncated.endswith("...")
    assert not truncated[:-3].endswith("foo")
    assert "foo_bar" not in truncated


def test_truncate_skill_guidance_does_not_split_a_hyphenated_token() -> None:
    """A cutoff before the hyphen in ``foo-bar-rest`` must back up to whitespace."""

    budget = _MAX_TOOL_SKILL_GUIDANCE_CHARS - 3
    text = "x" * (budget - 4) + " foo-bar-rest"
    assert len(text) > _MAX_TOOL_SKILL_GUIDANCE_CHARS
    truncated = _truncate_skill_guidance(text)
    assert truncated.endswith("...")
    assert not truncated[:-3].endswith("foo")
    assert "foo-bar" not in truncated


def test_truncate_skill_guidance_keeps_a_single_overlong_token() -> None:
    text = "x" * (_MAX_TOOL_SKILL_GUIDANCE_CHARS + 20)
    truncated = _truncate_skill_guidance(text)
    assert truncated.endswith("...")
    assert truncated[:-3] == "x" * (_MAX_TOOL_SKILL_GUIDANCE_CHARS - 3)


def test_apply_skill_guidance_skips_unknown_targets(
    tmp_path: Path, monkeypatch: Any, caplog: Any
) -> None:
    path = tmp_path / "SKILL.md"
    _write_skill(
        path,
        """
name: skip-unknown-target
description: Attach to one real tool and one missing name.
tools:
  - present_tool
  - missing_tool
""".strip(),
        body="Marker for skip-unknown-target.",
    )
    monkeypatch.setattr(
        "tools.registry_skill_guidance._skill_guidance_files",
        lambda: (path,),
    )
    tools_by_name = {"present_tool": _tool("present_tool"), "other_tool": _tool("other_tool")}
    with caplog.at_level(logging.WARNING, logger="tools.registry_skill_guidance"):
        apply_skill_guidance(tools_by_name, known_tool_names=frozenset(tools_by_name))

    assert "unknown_tool" in caplog.text
    assert "missing_tool" in caplog.text
    assert '<skill name="skip-unknown-target"' in tools_by_name["present_tool"].skill_guidance
    assert tools_by_name["other_tool"].skill_guidance == ""


def test_apply_skill_guidance_truncates_and_warns_when_over_budget(
    tmp_path: Path, monkeypatch: Any, caplog: Any
) -> None:
    body = "padding " * 800
    path = tmp_path / "SKILL.md"
    _write_skill(
        path,
        """
name: padded-over-budget
description: Force the registry cap.
tools:
  - present_tool
""".strip(),
        body=body,
    )
    monkeypatch.setattr(
        "tools.registry_skill_guidance._skill_guidance_files",
        lambda: (path,),
    )
    tools_by_name = {"present_tool": _tool("present_tool")}
    with caplog.at_level(logging.WARNING, logger="tools.registry_skill_guidance"):
        apply_skill_guidance(tools_by_name)

    guidance = tools_by_name["present_tool"].skill_guidance
    assert len(guidance) <= _MAX_TOOL_SKILL_GUIDANCE_CHARS
    assert guidance.endswith("...")
    assert "present_tool" in caplog.text
    assert "over the 2400-character budget" in caplog.text


def test_apply_skill_guidance_warns_when_two_sub_budget_skills_join_over_the_cap(
    tmp_path: Path, monkeypatch: Any, caplog: Any
) -> None:
    """Two skills under the cap targeting one tool still overrun once joined.

    Checking each skill in isolation misses this: both opening markers survive,
    the second body and closing tag are truncated, and no warning fires.
    """

    body = "padding " * 150
    first = tmp_path / "first" / "SKILL.md"
    second = tmp_path / "second" / "SKILL.md"
    first.parent.mkdir()
    second.parent.mkdir()
    _write_skill(
        first,
        """
name: sub-budget-one
description: First skill under the cap.
tools:
  - present_tool
""".strip(),
        body=body,
    )
    _write_skill(
        second,
        """
name: sub-budget-two
description: Second skill under the cap.
tools:
  - present_tool
""".strip(),
        body=body,
    )
    monkeypatch.setattr(
        "tools.registry_skill_guidance._skill_guidance_files",
        lambda: (first, second),
    )
    tools_by_name = {"present_tool": _tool("present_tool")}
    with caplog.at_level(logging.WARNING, logger="tools.registry_skill_guidance"):
        apply_skill_guidance(tools_by_name)

    first_skill = load_tool_skill_guidance(
        first, known_tool_names=frozenset({"present_tool"})
    ).skill
    second_skill = load_tool_skill_guidance(
        second, known_tool_names=frozenset({"present_tool"})
    ).skill
    assert first_skill is not None
    assert second_skill is not None
    first_formatted = format_tool_skill_guidance(first_skill)
    second_formatted = format_tool_skill_guidance(second_skill)
    assert len(first_formatted) <= _MAX_TOOL_SKILL_GUIDANCE_CHARS
    assert len(second_formatted) <= _MAX_TOOL_SKILL_GUIDANCE_CHARS
    assert len(first_formatted) + len(second_formatted) > _MAX_TOOL_SKILL_GUIDANCE_CHARS

    guidance = tools_by_name["present_tool"].skill_guidance
    assert '<skill name="sub-budget-one"' in guidance
    assert '<skill name="sub-budget-two"' in guidance
    assert len(guidance) <= _MAX_TOOL_SKILL_GUIDANCE_CHARS
    assert guidance.endswith("...")
    assert "</skill>" not in guidance.split('<skill name="sub-budget-two"', 1)[-1]
    assert "present_tool" in caplog.text
    assert "over the 2400-character budget" in caplog.text


def test_apply_skill_guidance_does_not_attach_disabled_skills(
    tmp_path: Path, monkeypatch: Any
) -> None:
    path = tmp_path / "SKILL.md"
    _write_skill(
        path,
        """
name: quiet-skill
description: Must not reach the model.
tools:
  - present_tool
disable-model-invocation: true
""".strip(),
        body="disabled body that must not attach.",
    )
    monkeypatch.setattr(
        "tools.registry_skill_guidance._skill_guidance_files",
        lambda: (path,),
    )
    tools_by_name = {"present_tool": _tool("present_tool")}
    apply_skill_guidance(tools_by_name)

    assert tools_by_name["present_tool"].skill_guidance == ""
    assert '<skill name="quiet-skill"' not in tools_by_name["present_tool"].description


def test_tree_inventory_skips_generated_output_and_ignores_ancestor_dir_names(
    tmp_path: Path,
) -> None:
    """PyInstaller copies and a parent named tests/.venv must not hide source skills."""

    repo = tmp_path / "tests" / ".venv" / "opensre"
    source = repo / "integrations" / "github" / "tools" / "workflow" / "SKILL.md"
    source.parent.mkdir(parents=True)
    generated = repo / "dist" / "opensre" / "_internal" / "SKILL.md"
    generated.parent.mkdir(parents=True)
    build_copy = repo / "build" / "opensre" / "SKILL.md"
    build_copy.parent.mkdir(parents=True)
    source.write_text("x", encoding="utf-8")
    generated.write_text("x", encoding="utf-8")
    build_copy.write_text("x", encoding="utf-8")

    assert not _skill_inventory_path_is_skipped(source, repo_root=repo)
    assert _skill_inventory_path_is_skipped(generated, repo_root=repo)
    assert _skill_inventory_path_is_skipped(build_copy, repo_root=repo)
