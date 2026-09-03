#!/usr/bin/env python3
"""Wait until the CI workflow's CI Gate job succeeds for a commit SHA."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

CI_WORKFLOW_FILE = "ci.yml"
CI_GATE_JOB_NAME = "CI Gate"
CI_PUSH_EVENT = "push"
DEFAULT_TIMEOUT_SECONDS = 4800
DEFAULT_POLL_SECONDS = 30
GITHUB_API = "https://api.github.com"
_TRANSIENT_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})

JsonGetter = Callable[[str, Mapping[str, str]], dict[str, Any]]
Verdict = Literal["success", "failure", "wait"]


class CiGateNotSuccessful(Exception):
    """CI Gate did not succeed for the requested SHA."""


class CiGateWaitTimeout(CiGateNotSuccessful):
    """Timed out before CI Gate reached a terminal result."""


class TransientApiError(Exception):
    """GitHub API returned a retryable error."""


@dataclass(frozen=True, slots=True)
class GateObservation:
    """One poll of the CI Gate job for a single SHA."""

    run_id: int | None
    job_status: str | None
    job_conclusion: str | None


def verdict(observation: GateObservation) -> Verdict:
    """Classify a poll: publish, refuse, or keep waiting."""
    if observation.run_id is None or observation.job_status is None:
        return "wait"
    if observation.job_status != "completed":
        return "wait"
    if observation.job_conclusion == "success":
        return "success"
    return "failure"


def newest_push_run(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the newest CI workflow run, or None when the SHA has none yet."""
    if not runs:
        return None
    return max(runs, key=lambda run: int(run.get("id") or 0))


def ci_gate_job(jobs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the CI Gate job from a workflow run, if it has been queued."""
    return next((job for job in jobs if job.get("name") == CI_GATE_JOB_NAME), None)


def observe_ci_gate(
    *,
    sha: str,
    get_json: JsonGetter,
    repo: str,
) -> GateObservation:
    """Load the newest push-event CI run for ``sha`` and read its CI Gate job."""
    runs_payload = get_json(
        f"/repos/{repo}/actions/workflows/{CI_WORKFLOW_FILE}/runs",
        {
            "head_sha": sha,
            "event": CI_PUSH_EVENT,
            "per_page": "20",
        },
    )
    run = newest_push_run(list(runs_payload.get("workflow_runs") or []))
    if run is None:
        return GateObservation(run_id=None, job_status=None, job_conclusion=None)

    run_id = int(run["id"])
    jobs_payload = get_json(
        f"/repos/{repo}/actions/runs/{run_id}/jobs",
        {"per_page": "100", "filter": "latest"},
    )
    job = ci_gate_job(list(jobs_payload.get("jobs") or []))
    if job is None:
        if run.get("status") == "completed":
            return GateObservation(
                run_id=run_id,
                job_status="completed",
                job_conclusion="missing",
            )
        return GateObservation(run_id=run_id, job_status=None, job_conclusion=None)

    conclusion = job.get("conclusion")
    return GateObservation(
        run_id=run_id,
        job_status=job.get("status"),
        job_conclusion=str(conclusion) if conclusion is not None else None,
    )


def wait_for_ci_gate(
    *,
    fetch: Callable[[], GateObservation],
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
    timeout_seconds: float,
    poll_seconds: float,
    log: Callable[[str], None] = print,
) -> GateObservation:
    """Poll ``fetch`` until CI Gate succeeds, or raise ``CiGateNotSuccessful``."""
    deadline = monotonic() + timeout_seconds
    while True:
        try:
            observation = fetch()
        except TransientApiError as exc:
            log(f"transient GitHub API error; retrying: {exc}")
            observation = GateObservation(run_id=None, job_status=None, job_conclusion=None)
        decision = verdict(observation)
        log(
            "CI Gate "
            f"run={observation.run_id} status={observation.job_status} "
            f"conclusion={observation.job_conclusion} verdict={decision}"
        )
        if decision == "success":
            return observation
        if decision == "failure":
            conclusion = observation.job_conclusion or "unknown"
            raise CiGateNotSuccessful(
                f"CI Gate concluded {conclusion!r} for this SHA; refusing to publish main-build"
            )
        if monotonic() >= deadline:
            raise CiGateWaitTimeout("timed out waiting for CI Gate to succeed for this SHA")
        sleep(poll_seconds)


def github_json_getter(token: str) -> JsonGetter:
    """Return a GET helper authenticated with ``token``."""

    def get_json(path: str, query: Mapping[str, str]) -> dict[str, Any]:
        url = f"{GITHUB_API}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "opensre-wait-for-ci-gate",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code in _TRANSIENT_HTTP_STATUSES:
                raise TransientApiError(f"HTTP {exc.code}") from exc
            raise
        except urllib.error.URLError as exc:
            raise TransientApiError(str(exc.reason)) from exc
        if not isinstance(payload, dict):
            raise TransientApiError("GitHub API returned a non-object payload")
        return payload

    return get_json


def main() -> int:
    """Poll CI Gate for ``WAIT_SHA``/``GITHUB_SHA`` and exit 0 only on success."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    sha = os.environ.get("WAIT_SHA") or os.environ.get("GITHUB_SHA", "")
    timeout_seconds = int(os.environ.get("WAIT_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    poll_seconds = int(os.environ.get("WAIT_POLL_SECONDS", DEFAULT_POLL_SECONDS))

    if not token:
        print("GITHUB_TOKEN is required", file=sys.stderr)
        return 1
    if not repo or "/" not in repo:
        print("GITHUB_REPOSITORY must be owner/repo", file=sys.stderr)
        return 1
    if not sha:
        print("WAIT_SHA or GITHUB_SHA is required", file=sys.stderr)
        return 1

    getter = github_json_getter(token)
    try:
        wait_for_ci_gate(
            fetch=lambda: observe_ci_gate(sha=sha, get_json=getter, repo=repo),
            sleep=time.sleep,
            monotonic=time.monotonic,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
        )
    except CiGateNotSuccessful as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
