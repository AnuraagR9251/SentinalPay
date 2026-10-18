"""Transparent account-takeover heuristic. Not a trained ATO model.

Needs labeled login, device, and credential-change events before a
separate classifier is honest. Missing GPS or device is not a hit.
"""

from __future__ import annotations

from risk.contracts import RuleResult, SecuritySignals, TriggeredRule

_ATO_RULES = frozenset({"NEW_DEVICE", "NEW_MERCHANT", "HIGH_VELOCITY", "IMPOSSIBLE_TRAVEL"})


def maybe_ato_rule(rules: RuleResult, security: SecuritySignals) -> TriggeredRule | None:
    names = {item.rule for item in rules.triggered_rules}
    hits = [name for name in _ATO_RULES if name in names]
    if any("device linked" in note for note in security.notes):
        hits.append("DEVICE_SHARED")
    if len(hits) < 2:
        return None
    return TriggeredRule(
        rule="ATO_SUSPECTED",
        severity="HIGH",
        score=22,
        reason="account-takeover heuristic: " + ", ".join(hits) + " (rules, not a trained ATO model)",
    )


def merge_ato(rules: RuleResult, security: SecuritySignals) -> RuleResult:
    extra = maybe_ato_rule(rules, security)
    if extra is None:
        return rules
    hits = rules.triggered_rules + (extra,)
    return RuleResult(rule_score=min(100, sum(item.score for item in hits)), triggered_rules=hits)
