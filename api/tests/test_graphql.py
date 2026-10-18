"""GraphQL wraps the same pipeline as REST."""

from fastapi.testclient import TestClient

from api.main import app


def _gql(client: TestClient, query: str, variables: dict | None = None, headers: dict | None = None):
    return client.post("/graphql", json={"query": query, "variables": variables or {}}, headers=headers or {})


SCORE_MUTATION = """
mutation Score($input: ScoreInput!) {
  scoreTransaction(input: $input) { transactionId canonicalDecision }
}
"""

EVAL_MUTATION = """
mutation Eval($input: EvaluateInput!) {
  evaluateTransaction(input: $input) { transactionId decision }
}
"""


def _score_vars(**overrides):
    body = {
        "transactionId": "gql-auth-score",
        "amount": 240.0,
        "payeeVpa": "kirana.lab@oksbi",
        "userId": "aarav@senitenial",
        "timestamp": "2026-09-28T11:00:00+00:00",
        "isNewPayee": False,
        "purpose": "groceries",
    }
    body.update(overrides)
    return {"input": body}


def _eval_vars(**overrides):
    body = {
        "userId": "aarav@senitenial",
        "amount": 240.0,
        "transactionId": "gql-auth-eval",
        "merchantId": "kirana.lab@oksbi",
        "merchantCategory": "groceries",
        "timestamp": "2026-09-28T11:00:00+00:00",
    }
    body.update(overrides)
    return {"input": body}


def test_graphql_health() -> None:
    client = TestClient(app)
    posted = _gql(client, "query { health { status modelLoaded modelVersion mlFallback } }")
    assert posted.status_code == 200
    health = posted.json()["data"]["health"]
    assert health["status"] == "ok"
    assert "modelLoaded" in health


def test_graphql_score_matches_rest() -> None:
    client = TestClient(app)
    payload = {
        "transaction_id": "gql-same-1",
        "amount": 1200.0,
        "payee_vpa": "shop.blr@oksbi",
        "user_id": "USR_GQL",
        "timestamp": "2026-09-28T11:00:00+00:00",
        "payer_location": {"lat": 12.9716, "lon": 77.5946},
        "is_new_payee": False,
        "purpose": "dining",
    }
    rest = client.post("/score", json=payload)
    assert rest.status_code == 200
    gql = _gql(
        client,
        """
        mutation Score($input: ScoreInput!) {
          scoreTransaction(input: $input) {
            transactionId
            riskScore
            riskTier
            canonicalDecision
            canonicalRiskScore
          }
        }
        """,
        {
            "input": {
                "transactionId": "gql-same-1",
                "amount": 1200.0,
                "payeeVpa": "shop.blr@oksbi",
                "userId": "USR_GQL",
                "timestamp": "2026-09-28T11:00:00+00:00",
                "payerLocation": {"lat": 12.9716, "lon": 77.5946},
                "isNewPayee": False,
                "purpose": "dining",
            }
        },
    )
    assert gql.status_code == 200
    body = gql.json()["data"]["scoreTransaction"]
    rest_body = rest.json()
    assert body["canonicalDecision"] == rest_body["canonical_decision"]
    assert body["canonicalRiskScore"] == rest_body["canonical_risk_score"]
    assert body["riskTier"] == rest_body["risk_tier"]


def test_graphql_evaluate() -> None:
    client = TestClient(app)
    posted = _gql(
        client,
        """
        mutation Eval($input: EvaluateInput!) {
          evaluateTransaction(input: $input) {
            transactionId
            decision
            riskScore
            locationBaseline
          }
        }
        """,
        {
            "input": {
                "userId": "USR_GQL_EVAL",
                "amount": 8500,
                "transactionId": "gql-eval-1",
                "merchantId": "MERCHANT_456",
                "merchantCategory": "electronics",
                "timestamp": "2026-09-28T10:30:00+00:00",
                "latitude": 12.9716,
                "longitude": 77.5946,
            }
        },
    )
    assert posted.status_code == 200
    body = posted.json()["data"]["evaluateTransaction"]
    assert body["decision"] in {"ALLOW", "REVIEW", "BLOCK"}
    assert 0 <= body["riskScore"] <= 100


def test_graphql_score_allows_missing_location() -> None:
    client = TestClient(app)
    posted = _gql(
        client,
        """
        mutation Score($input: ScoreInput!) {
          scoreTransaction(input: $input) {
            transactionId
            canonicalDecision
            pAe
            aeAvailable
          }
        }
        """,
        {
            "input": {
                "transactionId": "gql-noloc-1",
                "amount": 240.0,
                "payeeVpa": "kirana.lab@oksbi",
                "userId": "USR_GQL_NOLOC",
                "timestamp": "2026-09-28T11:00:00+00:00",
                "isNewPayee": False,
                "purpose": "groceries",
            }
        },
    )
    assert posted.status_code == 200
    body = posted.json()["data"]["scoreTransaction"]
    assert body["transactionId"] == "gql-noloc-1"
    assert body["canonicalDecision"] in {"ALLOW", "REVIEW", "BLOCK"}
    assert body["pAe"] is None
    assert body["aeAvailable"] is False


def test_graphql_open_demo_allows_both_mutations() -> None:
    client = TestClient(app)
    score = _gql(client, SCORE_MUTATION, _score_vars(transactionId="gql-open-score"))
    evaluate = _gql(client, EVAL_MUTATION, _eval_vars(transactionId="gql-open-eval"))
    assert score.status_code == 200
    assert evaluate.status_code == 200
    assert score.json()["data"]["scoreTransaction"]["transactionId"] == "gql-open-score"
    assert evaluate.json()["data"]["evaluateTransaction"]["transactionId"] == "gql-open-eval"


def test_graphql_login_required_blocks_both_mutations(monkeypatch) -> None:
    monkeypatch.setenv("SENTINALPAY_REQUIRE_LOGIN", "1")
    client = TestClient(app)
    score = _gql(client, SCORE_MUTATION, _score_vars(transactionId="gql-denied-score"))
    evaluate = _gql(client, EVAL_MUTATION, _eval_vars(transactionId="gql-denied-eval"))
    assert score.json()["data"] is None or score.json()["data"]["scoreTransaction"] is None
    assert evaluate.json()["data"] is None or evaluate.json()["data"]["evaluateTransaction"] is None
    assert score.json()["errors"]
    assert evaluate.json()["errors"]


def test_graphql_invalid_session_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("SENTINALPAY_REQUIRE_LOGIN", "1")
    client = TestClient(app)
    posted = _gql(
        client,
        SCORE_MUTATION,
        _score_vars(transactionId="gql-bad-session"),
        headers={"Authorization": "Bearer not-a-real-session"},
    )
    assert posted.json()["errors"]
    assert posted.json()["data"] is None or posted.json()["data"]["scoreTransaction"] is None


def test_graphql_user_mismatch_rejected(monkeypatch) -> None:
    monkeypatch.setenv("SENTINALPAY_REQUIRE_LOGIN", "1")
    client = TestClient(app)
    token = client.post("/login", json={"user_id": "aarav@senitenial", "password": "demo123"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    score = _gql(
        client,
        SCORE_MUTATION,
        _score_vars(transactionId="gql-mismatch-s", userId="priya@senitenial"),
        headers=headers,
    )
    evaluate = _gql(
        client,
        EVAL_MUTATION,
        _eval_vars(transactionId="gql-mismatch-e", userId="priya@senitenial"),
        headers=headers,
    )
    assert "mismatch" in score.json()["errors"][0]["message"].lower()
    assert "mismatch" in evaluate.json()["errors"][0]["message"].lower()


def test_graphql_authenticated_score_and_evaluate(monkeypatch) -> None:
    monkeypatch.setenv("SENTINALPAY_REQUIRE_LOGIN", "1")
    client = TestClient(app)
    token = client.post("/login", json={"user_id": "aarav@senitenial", "password": "demo123"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    score = _gql(client, SCORE_MUTATION, _score_vars(transactionId="gql-ok-score"), headers=headers)
    evaluate = _gql(client, EVAL_MUTATION, _eval_vars(transactionId="gql-ok-eval"), headers=headers)
    assert score.json()["data"]["scoreTransaction"]["transactionId"] == "gql-ok-score"
    assert evaluate.json()["data"]["evaluateTransaction"]["transactionId"] == "gql-ok-eval"
