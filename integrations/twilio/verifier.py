"""Twilio integration verifier: account auth + SMS channel readiness.

A "passed" result confirms the account credentials authenticate and the
SMS channel has a usable sender (``from_number`` or
``messaging_service_sid``). WhatsApp is verified separately via the
standalone ``whatsapp`` integration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from integrations.probes import ProbeStatus
from integrations.verification import register_verifier, result


@dataclass(frozen=True)
class TwilioValidationResult:
    """Outcome of validating Twilio credentials and SMS channel readiness.

    ``status`` is the discriminator: a missing credential (``MISSING``) is
    distinct from an API or SMS-channel failure (``FAILED``) without parsing
    ``detail``. ``ok`` is the posthog-style pass/fail view derived from it,
    so callers that only need "did it pass" read ``ok`` exactly like
    :class:`integrations.posthog.verifier.PostHogValidationResult`.
    """

    status: ProbeStatus
    detail: str

    @property
    def ok(self) -> bool:
        return self.status is ProbeStatus.PASSED


def validate_twilio_config(config: dict[str, Any]) -> TwilioValidationResult:
    """Authenticate the Twilio account and confirm the SMS channel is ready."""
    account_sid = str(config.get("account_sid", "")).strip()
    auth_token = str(config.get("auth_token", "")).strip()
    if not account_sid:
        return TwilioValidationResult(status=ProbeStatus.MISSING, detail="Missing account_sid.")
    if not auth_token:
        return TwilioValidationResult(status=ProbeStatus.MISSING, detail="Missing auth_token.")

    try:
        response = requests.get(
            f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}.json",
            auth=(account_sid, auth_token),
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return TwilioValidationResult(
            status=ProbeStatus.FAILED, detail=f"Twilio API check failed: {exc}"
        )

    friendly_name = str(payload.get("friendly_name", "")).strip() or account_sid

    sms_cfg = config.get("sms") or {}
    sms_ready = bool(sms_cfg.get("enabled")) and bool(
        str(sms_cfg.get("from_number") or "").strip()
        or str(sms_cfg.get("messaging_service_sid") or "").strip()
    )

    if not sms_ready:
        return TwilioValidationResult(
            status=ProbeStatus.FAILED,
            detail=(
                f"Connected to Twilio account {friendly_name} but the SMS channel "
                "is not ready. Enable SMS and set a from_number or messaging_service_sid."
            ),
        )

    return TwilioValidationResult(
        status=ProbeStatus.PASSED,
        detail=f"Connected to Twilio account {friendly_name}; SMS channel ready.",
    )


@register_verifier("twilio")
def verify_twilio(source: str, config: dict[str, Any]) -> dict[str, str]:
    """Edge adapter: run the typed validation and convert at the registry boundary.

    The registry contract is ``dict[str, str]`` (shared by all 64 verifiers);
    the typed :class:`TwilioValidationResult` is an internal detail converted
    here so the contract stays unchanged for everyone else.
    """
    validation = validate_twilio_config(config)
    return result("twilio", source, validation.status.value, validation.detail)
