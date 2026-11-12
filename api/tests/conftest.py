"""Isolate HTTP tests on a temp SQLite store."""

from __future__ import annotations

import pytest

from api.tests.desk_auth import DESK_PASSWORD, DESK_USER
from risk.store import reset_store


@pytest.fixture(autouse=True)
def isolated_risk_store(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTINALPAY_DATABASE_URL", f"sqlite:///{(tmp_path / 'phase1.db').as_posix()}")
    monkeypatch.setenv("SENTINALPAY_HIGH_RISK_CATEGORIES", "gambling,crypto,jewelry")
    monkeypatch.setenv("SENTINALPAY_PBKDF2_ROUNDS", "2")
    monkeypatch.setenv("SENTINALPAY_REQUIRE_LOGIN", "0")
    monkeypatch.setenv("SENTINALPAY_API_KEY", "")
    monkeypatch.setenv("SENTINALPAY_ADMIN_USERNAME", DESK_USER)
    monkeypatch.setenv("SENTINALPAY_ADMIN_PASSWORD", DESK_PASSWORD)
    monkeypatch.setenv("SENTINALPAY_ARGON2_TIME", "1")
    monkeypatch.setenv("SENTINALPAY_ARGON2_MEMORY", "8")
    monkeypatch.setenv("SENTINALPAY_COOKIE_SECURE", "0")
    reset_store()
    yield
    reset_store()
