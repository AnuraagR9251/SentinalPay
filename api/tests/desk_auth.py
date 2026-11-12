"""Shared desk-admin sign-in for API tests. Password is a fixture, not a deployment secret."""

DESK_USER = "desk"
DESK_PASSWORD = "desk-pass-1"
CSRF = {"X-SentinalPay-Admin": "1"}


def sign_in_desk(client):
    response = client.post(
        "/admin/login",
        json={"username": DESK_USER, "password": DESK_PASSWORD},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["username"] == DESK_USER
    assert "token" not in body
    assert DESK_PASSWORD not in response.text
    return response
