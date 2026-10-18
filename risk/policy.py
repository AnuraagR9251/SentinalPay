"""Action policy after the canonical ALLOW / REVIEW / BLOCK decision.

STEP_UP is not a rename of REVIEW. It is a follow-up action for mid-band
REVIEW plus a first-time merchant or device.
"""

from __future__ import annotations

from typing import Any, Mapping


def policy_action(result: Mapping[str, Any]) -> str:
    decision = str(result.get("decision") or "REVIEW")
    if decision == "ALLOW":
        return "ALLOW"
    if decision == "BLOCK":
        return "BLOCK"
    names = {item.get("rule") for item in (result.get("rules") or {}).get("triggered_rules") or []}
    if "NEW_MERCHANT" in names or "NEW_DEVICE" in names:
        return "STEP_UP"
    return "HOLD"
