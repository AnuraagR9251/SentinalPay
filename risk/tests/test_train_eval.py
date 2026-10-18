"""Training split and review-objective helpers (no PaySim download)."""

from datetime import datetime, timedelta, timezone

import pandas as pd

from ml.train_xgboost import chronological_thirds, review_operating_point, _leakage_correlations
import numpy as np


def test_chronological_thirds_are_ordered() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [
        {"_ts": start + timedelta(days=i), "_y": int(i == 9), "amount_spike": 0.1 * i}
        for i in range(10)
    ]
    train, val, test = chronological_thirds(pd.DataFrame(rows))
    assert train["_ts"].max() <= val["_ts"].min()
    assert val["_ts"].max() <= test["_ts"].min()
    assert len(train) == 6 and len(val) == 2 and len(test) == 2


def test_review_operating_point_counts_catch_and_extra() -> None:
    y = np.array([1, 1, 0, 0, 0])
    scores = np.array([0.9, 0.2, 0.8, 0.1, 0.0])
    out = review_operating_point(y, scores, 0.5)
    assert out["fraud_caught"] == 1
    assert out["fraud_recall"] == 0.5
    assert abs(out["legit_review_rate"] - 1 / 3) < 1e-9


def test_leakage_flags_perfect_copy() -> None:
    frame = pd.DataFrame({"_y": [0, 0, 1, 1], "copy": [0.0, 0.0, 1.0, 1.0], "noise": [0.1, 0.2, 0.1, 0.2]})
    corr = _leakage_correlations(frame, ["copy", "noise"])
    assert abs(corr["copy"]) > 0.9
    assert abs(corr["noise"]) < 0.9
