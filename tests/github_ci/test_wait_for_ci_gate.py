"""Decision contracts for same-SHA CI Gate gating of main-build publication."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Mapping
from typing import Any

import pytest

from config.constants.paths import REPO_ROOT

_MODULE_PATH = REPO_ROOT / ".github" / "scripts" / "wait_for_ci_gate.py"
_spec = importlib.util.spec_from_file_location("wait_for_ci_gate", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
_script = importlib.util.module_from_spec(_spec)
sys.modules["wait_for_ci_gate"] = _script
_spec.loader.exec_module(_script)

CiGateNotSuccessful = _script.CiGateNotSuccessful
CiGateWaitTimeout = _script.CiGateWaitTimeout
GateObservation = _script.GateObservation
TransientApiError = _script.TransientApiError
observe_ci_gate = _script.observe_ci_gate
verdict = _script.verdict
wait_until = _script.wait_for_ci_gate

_SHA = "4b20a0d0123456789abcdef0123456789abcdef0"
_REPO = "Tracer-Cloud/opensre"


def _get_json_for(
    runs: list[dict[str, Any]],
    jobs_by_run: Mapping[int, list[dict[str, Any]]],
) -> _script.JsonGetter:
    def get_json(path: str, query: Mapping[str, str]) -> dict[str, Any]:
        if path.endswith("/runs"):
            assert query["head_sha"] == _SHA
            assert query["event"] == "push"
            return {"workflow_runs": runs}
        run_id = int(path.split("/")[-2])
        return {"jobs": list(jobs_by_run[run_id])}

    return get_json


def test_verdict_waits_until_ci_gate_completes() -> None:
    assert verdict(GateObservation(None, None, None)) == "wait"
    assert verdict(GateObservation(1, "in_progress", None)) == "wait"
    assert verdict(GateObservation(1, "completed", "success")) == "success"


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "skipped", "timed_out", "missing"])
def test_verdict_refuses_terminal_non_success(conclusion: str) -> None:
    assert verdict(GateObservation(1, "completed", conclusion)) == "failure"


def test_observe_uses_newest_push_run_for_the_requested_sha() -> None:
    runs = [
        {"id": 10, "status": "completed", "head_sha": _SHA},
        {"id": 20, "status": "completed", "head_sha": _SHA},
    ]
    jobs = {
        10: [{"name": "CI Gate", "status": "completed", "conclusion": "failure"}],
        20: [{"name": "CI Gate", "status": "completed", "conclusion": "success"}],
    }

    observation = observe_ci_gate(sha=_SHA, get_json=_get_json_for(runs, jobs), repo=_REPO)

    assert observation == GateObservation(20, "completed", "success")
    assert verdict(observation) == "success"


def test_observe_fail_closes_when_completed_run_has_no_ci_gate_job() -> None:
    runs = [{"id": 7, "status": "completed"}]
    observation = observe_ci_gate(sha=_SHA, get_json=_get_json_for(runs, {7: []}), repo=_REPO)

    assert observation == GateObservation(7, "completed", "missing")
    assert verdict(observation) == "failure"


def test_observe_waits_while_ci_gate_has_not_queued() -> None:
    runs = [{"id": 7, "status": "in_progress"}]
    observation = observe_ci_gate(sha=_SHA, get_json=_get_json_for(runs, {7: []}), repo=_REPO)

    assert observation == GateObservation(7, None, None)
    assert verdict(observation) == "wait"


def test_wait_succeeds_after_in_progress_polls() -> None:
    polls = iter(
        [
            GateObservation(1, "in_progress", None),
            GateObservation(1, "completed", "success"),
        ]
    )
    sleeps: list[float] = []
    clock = iter([0.0, 1.0, 2.0])

    result = wait_until(
        fetch=lambda: next(polls),
        sleep=sleeps.append,
        monotonic=lambda: next(clock),
        timeout_seconds=30,
        poll_seconds=5,
        log=lambda _message: None,
    )

    assert result.job_conclusion == "success"
    assert sleeps == [5]


def test_wait_refuses_cancelled_or_failed_ci_gate() -> None:
    with pytest.raises(CiGateNotSuccessful, match="cancelled"):
        wait_until(
            fetch=lambda: GateObservation(1, "completed", "cancelled"),
            sleep=lambda _seconds: None,
            monotonic=lambda: 0.0,
            timeout_seconds=30,
            poll_seconds=5,
            log=lambda _message: None,
        )


def test_wait_times_out_when_ci_gate_never_appears() -> None:
    clock = iter([0.0, 30.0])

    with pytest.raises(CiGateWaitTimeout):
        wait_until(
            fetch=lambda: GateObservation(None, None, None),
            sleep=lambda _seconds: None,
            monotonic=lambda: next(clock),
            timeout_seconds=30,
            poll_seconds=5,
            log=lambda _message: None,
        )


def test_wait_retries_transient_api_errors_then_succeeds() -> None:
    calls = {"n": 0}

    def fetch() -> GateObservation:
        calls["n"] += 1
        if calls["n"] == 1:
            raise TransientApiError("HTTP 502")
        return GateObservation(3, "completed", "success")

    result = wait_until(
        fetch=fetch,
        sleep=lambda _seconds: None,
        monotonic=lambda: 0.0,
        timeout_seconds=30,
        poll_seconds=5,
        log=lambda _message: None,
    )

    assert result.run_id == 3
