"""GraphQL wraps the same pipeline as REST."""

from fastapi.testclient import TestClient

from api.main import app


def _gql(client: TestClient, query: str, variables: dict | None = None):
    return client.post("/graphql", json={"query": query, "variables": variables or {}})


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
