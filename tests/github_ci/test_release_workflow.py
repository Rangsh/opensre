"""Workflow contracts for rolling main-build publication."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[2]
_WAIT_SCRIPT = ".github/scripts/wait_for_ci_gate.py"


def _workflow(name: str) -> dict[str, Any]:
    return yaml.safe_load(_ROOT.joinpath(".github", "workflows", name).read_text(encoding="utf-8"))


def test_publish_main_release_requires_same_sha_ci_gate_success() -> None:
    jobs = _workflow("release.yml")["jobs"]
    wait = jobs["wait-for-ci-gate"]
    publish = jobs["publish-main-release"]

    assert wait["needs"] == "prepare"
    assert wait["if"] == "needs.prepare.outputs.channel == 'main'"
    wait_step = next(
        step for step in wait["steps"] if step.get("name") == "Wait for CI Gate on this SHA"
    )
    assert wait_step["run"] == f"python3 {_WAIT_SCRIPT}"
    assert wait_step["env"]["WAIT_SHA"] == "${{ github.sha }}"
    assert "continue-on-error" not in wait
    assert "continue-on-error" not in wait_step

    assert set(publish["needs"]) == {"prepare", "build-binaries", "wait-for-ci-gate"}
    publish_if = " ".join(publish["if"].split())
    assert "needs.wait-for-ci-gate.result == 'success'" in publish_if
    assert "needs.build-binaries.result == 'success'" in publish_if
    assert "needs.prepare.outputs.channel == 'main'" in publish_if
    assert "needs.wait-for-ci-gate.result == 'skipped'" not in publish_if
    assert "needs.wait-for-ci-gate.result == 'failure'" not in publish_if
    assert "needs.wait-for-ci-gate.result == 'cancelled'" not in publish_if


def test_failed_wait_does_not_move_main_build_assets() -> None:
    jobs = _workflow("release.yml")["jobs"]
    publish = jobs["publish-main-release"]
    tag_step = next(
        step
        for step in publish["steps"]
        if step.get("name") == "Move main build tag to the latest commit"
    )
    notes_step = next(
        step for step in publish["steps"] if step.get("name") == "Publish rolling main release"
    )

    assert "git tag -f" in tag_step["run"]
    assert "gh release upload" in notes_step["run"]
    assert "gh release create" in notes_step["run"]
    assert "wait-for-ci-gate" in publish["needs"]
    assert "needs.wait-for-ci-gate.result == 'success'" in " ".join(publish["if"].split())


def test_stable_releases_remain_independent_of_the_ci_gate_wait() -> None:
    jobs = _workflow("release.yml")["jobs"]
    triggers = _workflow("release.yml")[True]

    assert "schedule" in triggers
    assert "workflow_dispatch" in triggers
    assert jobs["verify"]["if"] == "github.event_name != 'push'"
    assert jobs["publish-release"]["if"] == "needs.prepare.outputs.channel == 'release'"
    assert "wait-for-ci-gate" not in jobs["publish-release"]["needs"]
    assert "wait-for-ci-gate" not in jobs["verify"].get("needs", [])
    assert "wait-for-ci-gate" not in jobs["build-python-dist"]["needs"]
