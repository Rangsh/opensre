"""Keep the live selection suite gated, and this shard collectable on fork PRs."""

from __future__ import annotations

from tests.tools.selection import test_tool_selection as selection_tests


def test_tool_selection_suite_is_marked_live_llm() -> None:
    """Fork CI skips ``live_llm``; this unmarked pin keeps the shard from collecting 0 tests."""
    names = {mark.name for mark in selection_tests.pytestmark}
    assert "live_llm" in names
