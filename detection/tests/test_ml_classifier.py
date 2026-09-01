"""Tests for purpose-risk features and the ML inference wrapper."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from xgboost import XGBClassifier

from detection.ml_classifier import classify_payment, reset_model_cache
from detection.models import PaymentRiskLabel, Transaction
from ml.features import FEATURE_NAMES, LABEL_TO_ID, normalise_purpose, vector_from_transaction


def _txn(**overrides: object) -> Transaction:
    base = dict(
        transaction_id="txn_ml",
        user_id="user_ml",
        amount=250.0,
        payee_vpa="kirana@oksbi",
        timestamp=datetime(2026, 6, 15, 11, 0, tzinfo=timezone.utc),
        purpose="merchant_payment",
        origin_balance=8000.0,
        new_origin_balance=7750.0,
    )
    base.update(overrides)
    return Transaction(**base)  # type: ignore[arg-type]


def test_purpose_mapping_from_paysim_and_upi() -> None:
    assert normalise_purpose(paysim_type="CASH_OUT") == "cash_out"
    assert normalise_purpose(upi_type="Peer Transfer") == "p2p_transfer"
    assert normalise_purpose(category="Groceries") == "merchant_payment"
    assert normalise_purpose(category="Salary") == "salary"


def test_feature_vector_has_stable_width_without_balances() -> None:
    with_ledger = vector_from_transaction(_txn())
    bare = vector_from_transaction(_txn(origin_balance=None, new_origin_balance=None))
    assert with_ledger.shape == (len(FEATURE_NAMES),)
    assert bare.shape == with_ledger.shape
    assert bare[list(FEATURE_NAMES).index("has_balances")] == 0.0


def test_classify_payment_on_tiny_trained_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rng = np.random.default_rng(0)
    # Synthetic linearly separable-ish 3-class toy set on the real feature width.
    x = rng.normal(size=(90, len(FEATURE_NAMES))).astype(np.float32)
    y = np.array([0] * 30 + [1] * 30 + [2] * 30)
    x[:30, 0] = 100
    x[30:60, 0] = 20_000
    x[60:, 0] = 200_000
    model = XGBClassifier(
        n_estimators=20,
        max_depth=3,
        objective="multi:softprob",
        num_class=3,
        verbosity=0,
    )
    model.fit(x, y)
    model_path = tmp_path / "payment_risk_xgb.json"
    meta_path = tmp_path / "model_meta.json"
    model.save_model(model_path)
    meta_path.write_text(
        json.dumps(
            {
                "feature_names": list(FEATURE_NAMES),
                "id_to_label": {str(idx): name for name, idx in LABEL_TO_ID.items()},
                "category_medians": {},
            }
        ),
        encoding="utf-8",
    )
    import detection.ml_classifier as clf

    monkeypatch.setattr(clf, "MODEL_PATH", model_path)
    monkeypatch.setattr(clf, "META_PATH", meta_path)
    reset_model_cache()
    prediction = classify_payment(_txn(amount=200_000.0, purpose="cash_out", origin_balance=200_000.0, new_origin_balance=0.0))
    assert prediction is not None
    assert prediction.label in PaymentRiskLabel
    assert abs(sum(p for _, p in prediction.probabilities) - 1.0) < 1e-5
    reset_model_cache()
