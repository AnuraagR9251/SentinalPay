from risk.policy import policy_action


def test_review_plus_new_merchant_is_step_up() -> None:
    action = policy_action(
        {
            "decision": "REVIEW",
            "rules": {"triggered_rules": [{"rule": "NEW_MERCHANT"}]},
        }
    )
    assert action == "STEP_UP"


def test_review_without_new_party_is_hold() -> None:
    assert policy_action({"decision": "REVIEW", "rules": {"triggered_rules": []}}) == "HOLD"


def test_allow_and_block_stay_canonical() -> None:
    assert policy_action({"decision": "ALLOW"}) == "ALLOW"
    assert policy_action({"decision": "BLOCK"}) == "BLOCK"
