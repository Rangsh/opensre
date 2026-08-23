"""Attach SKILL.md workflow guidance to discovered tools.

The registry facade (:mod:`tools.registry`) calls :func:`apply_skill_guidance`
after collecting tools so a tool's description carries the workflow guidance the
matching SKILL.md declares for it.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from config.constants.paths import REPO_ROOT
from core.tool import RegisteredTool
from core.tool_framework import format_tool_skill_guidance, load_tool_skill_guidance

logger = logging.getLogger(__name__)

_MAX_TOOL_SKILL_GUIDANCE_CHARS = 2400


def _skill_guidance_files() -> tuple[Path, ...]:
    """Return explicit and package-local SKILL.md files attached at registry load."""

    explicit = (
        REPO_ROOT / "integrations" / "github" / "tools" / "workflow" / "SKILL.md",
        REPO_ROOT / "integrations" / "sentry" / "tools" / "skills" / "sentry-summary" / "SKILL.md",
        REPO_ROOT
        / "integrations"
        / "posthog"
        / "tools"
        / "skills"
        / "posthog-summary"
        / "SKILL.md",
        REPO_ROOT / "integrations" / "github" / "tools" / "github_cli" / "SKILL.md",
        REPO_ROOT / "integrations" / "github" / "tools" / "ci_fix" / "SKILL.md",
        REPO_ROOT / "integrations" / "github" / "tools" / "security_fix" / "SKILL.md",
        REPO_ROOT / "integrations" / "yandex_cloud" / "tools" / "SKILL.md",
    )
    discovered = sorted(
        (REPO_ROOT / "tools" / "system" / "python_execution_tool" / "skills").glob("*/SKILL.md")
    )
    return (*explicit, *discovered)


def _is_token_char(ch: str) -> bool:
    """Return whether ``ch`` continues an identifier-like token (e.g. ``foo_bar``)."""

    return ch.isalnum() or ch == "_"


def _truncate_skill_guidance(text: str) -> str:
    """Cap guidance at ``_MAX_TOOL_SKILL_GUIDANCE_CHARS``, ending on a word when possible."""

    if len(text) <= _MAX_TOOL_SKILL_GUIDANCE_CHARS:
        return text
    budget = _MAX_TOOL_SKILL_GUIDANCE_CHARS - 3
    chopped = text[:budget]
    # Back up to the last whitespace when the slice splits a token. A slice with
    # no whitespace is left as-is — cutting mid-word is then unavoidable.
    if (
        chopped
        and _is_token_char(chopped[-1])
        and budget < len(text)
        and _is_token_char(text[budget])
    ):
        boundary = max(chopped.rfind(" "), chopped.rfind("\n"), chopped.rfind("\t"))
        if boundary > 0:
            chopped = chopped[:boundary]
    return chopped.rstrip() + "..."


def _with_skill_guidance(tool: RegisteredTool, guidance: str) -> RegisteredTool:
    if not guidance:
        return tool
    return replace(
        tool,
        description=f"{tool.description}\n\nWorkflow guidance:\n{guidance}",
        skill_guidance=guidance,
    )


def apply_skill_guidance(
    tools_by_name: dict[str, RegisteredTool],
    *,
    known_tool_names: frozenset[str] | None = None,
) -> None:
    # Diagnostics validate against the full tool set (a surface load holds only a
    # subset); guidance still attaches only to tools present in ``tools_by_name``.
    diagnostic_names = (
        known_tool_names if known_tool_names is not None else frozenset(tools_by_name)
    )
    guidance_by_tool: dict[str, list[str]] = {}
    over_budget: list[str] = []

    for skill_path in _skill_guidance_files():
        result = load_tool_skill_guidance(skill_path, known_tool_names=diagnostic_names)
        for diagnostic in result.diagnostics:
            logger.warning(
                "[tools] Skill guidance %s (%s): %s",
                diagnostic.path,
                diagnostic.code,
                diagnostic.message,
            )
        skill = result.skill
        if skill is None or skill.disable_model_invocation:
            continue
        guidance = format_tool_skill_guidance(skill)
        if len(guidance) > _MAX_TOOL_SKILL_GUIDANCE_CHARS:
            over_budget.append(f"{skill.name} ({len(guidance)} chars)")
        for tool_name in skill.tool_names:
            if tool_name not in tools_by_name:
                continue
            guidance_by_tool.setdefault(tool_name, []).append(guidance)

    if over_budget:
        logger.warning(
            "[tools] Skill guidance over the %s-character budget: %s",
            _MAX_TOOL_SKILL_GUIDANCE_CHARS,
            ", ".join(over_budget),
        )

    for tool_name, guidances in guidance_by_tool.items():
        combined = _truncate_skill_guidance("\n\n".join(guidances))
        tools_by_name[tool_name] = _with_skill_guidance(tools_by_name[tool_name], combined)
