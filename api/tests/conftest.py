"""Isolate HTTP tests on a temp SQLite store."""

from __future__ import annotations

import pytest

from risk.store import reset_store


@pytest.fixture(autouse=True)
def isolated_risk_store(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTINALPAY_DATABASE_URL", f"sqlite:///{(tmp_path / 'phase1.db').as_posix()}")
    monkeypatch.setenv("SENTINALPAY_HIGH_RISK_CATEGORIES", "gambling,crypto,jewelry")
    monkeypatch.setenv("SENTINALPAY_PBKDF2_ROUNDS", "2")
    monkeypatch.setenv("SENTINALPAY_REQUIRE_LOGIN", "0")
    monkeypatch.setenv("SENTINALPAY_API_KEY", "")
    reset_store()
    yield
    reset_store()
