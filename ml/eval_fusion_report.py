"""Say whether a fair fusion comparison can be computed. Does not invent metrics.

PaySim is not in git. Graph scores are a heuristic over a 24h payment graph,
which PaySim's hourly steps and fraud labels do not match, so that comparison
is not run even when the CSV is present.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from detection.graph_features import add_transaction, empty_graph, score_graph  # noqa: E402
from detection.scoring_engine import FEATURE_VECTOR_NAMES  # noqa: E402

PAYSIM = REPO_ROOT / "dataset" / "PS_20174392719_1491204439457_log.csv"
UPI = REPO_ROOT / "dataset" / "upi_transactions_2025.csv"


def _latency() -> dict:
    graph = empty_graph()
    add_transaction(
        graph,
        {
            "transaction_id": "lat-1",
            "user_id": "payer",
            "payee_vpa": "payee@upi",
            "amount": 100.0,
            "timestamp": "2026-09-28T12:00:00+00:00",
        },
    )
    started = time.perf_counter()
    for _ in range(100):
        score_graph(graph, "payer")
    graph_ms = (time.perf_counter() - started) * 1000.0 / 100.0
    from detection.autoencoder_scorer import infer_autoencoder

    vector = {name: 0.0 for name in FEATURE_VECTOR_NAMES}
    started = time.perf_counter()
    first = infer_autoencoder(vector)
    first_ms = (time.perf_counter() - started) * 1000.0
    started = time.perf_counter()
    second = infer_autoencoder(vector)
    second_ms = (time.perf_counter() - started) * 1000.0
    return {
        "graph_heuristic_ms": round(graph_ms, 3),
        "autoencoder_first_call_ms": round(first_ms, 1),
        "autoencoder_second_call_ms": round(second_ms, 1),
        "autoencoder_available": first.available and second.available,
        "autoencoder_error": first.error,
        "autoencoder_score_present": first.score is not None,
    }


def _ranking(y_true, scores) -> dict:
    import numpy as np
    from sklearn.metrics import average_precision_score, roc_auc_score

    y = np.asarray(y_true)
    s = np.asarray(scores, dtype=np.float64)
    if len(np.unique(y)) < 2:
        return {"roc_auc": None, "average_precision": None}
    return {
        "roc_auc": float(roc_auc_score(y, s)),
        "average_precision": float(average_precision_score(y, s)),
    }


def _comparative() -> dict:
    """Score the saved models on the newest chronological fifth. No new threshold search."""
    import json

    import joblib
    import numpy as np

    from detection.scoring_engine import FEATURE_VECTOR_NAMES as ae_names
    from ml.train_xgboost import LIVE_FEATURE_NAMES, MODEL_PATH, build_feature_frames
    from ml.xgb_eval import chronological_thirds, pack_clf_metrics

    paysim, _upi = build_feature_frames()
    _train, _val, test_df = chronological_thirds(paysim)
    y_test = test_df["_y"].to_numpy(dtype=np.int32)
    saved = json.loads((REPO_ROOT / "ml" / "models" / "xgboost_metrics.json").read_text(encoding="utf-8"))
    threshold = float(saved["threshold"])
    loaded = joblib.load(MODEL_PATH)
    xgb = loaded["model"] if isinstance(loaded, dict) else loaded
    names = list(loaded.get("feature_names") or LIVE_FEATURE_NAMES) if isinstance(loaded, dict) else list(LIVE_FEATURE_NAMES)
    p_xgb = xgb.predict_proba(test_df[names].to_numpy(dtype=np.float32))[:, 1]
    xgb_metrics = pack_clf_metrics(y_test, p_xgb, threshold)

    import os

    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    from tensorflow import keras

    ae = keras.models.load_model(REPO_ROOT / "ml" / "models" / "autoencoder_model.keras")
    matrix = test_df[list(ae_names)].to_numpy(dtype=np.float32)
    predicted = ae.predict(matrix, batch_size=256, verbose=0)
    errors = np.mean(np.square(matrix - predicted), axis=1)
    ae_rank = _ranking(y_test, errors)
    return {
        "split": "chronological_60_20_20_test",
        "test_rows": int(len(y_test)),
        "test_fraud": int(y_test.sum()),
        "A_xgboost_only": {
            "threshold_source": "saved validation threshold; not refit on this run",
            "threshold": threshold,
            **{key: xgb_metrics[key] for key in ("roc_auc", "average_precision", "precision", "recall", "fpr", "confusion")},
            "legitimate_approval_rate": float(xgb_metrics["confusion"]["tn"] / max(1, xgb_metrics["confusion"]["tn"] + xgb_metrics["confusion"]["fp"])),
            "fraud_detection_rate": xgb_metrics["recall"],
        },
        "B_autoencoder_ranking": {
            "score": "reconstruction MSE on the 10 autoencoder features",
            "threshold_fit": "none — ROC-AUC and PR-AUC do not use a cut",
            "note": (
                "The saved p95 threshold was fit on this same newest slice, so precision "
                "and recall at that cut are not reported."
            ),
            **ae_rank,
        },
        "C_graph": None,
        "D_xgboost_autoencoder_graph": None,
        "E_hybrid_policy": None,
    }


def main() -> dict:
    paysim = PAYSIM.is_file()
    comparisons = {
        "A_xgboost_only": None,
        "B_xgboost_autoencoder": None,
        "C_xgboost_graph": None,
        "D_xgboost_autoencoder_graph": None,
        "E_hybrid_autoencoder_graph": None,
    }
    scored = None
    limitation = (
        "PaySim CSV is not on disk, so ROC-AUC, PR-AUC, precision, recall, "
        "false-positive rate, and confusion counts were not computed."
    )
    if paysim:
        scored = _comparative()
        comparisons["A_xgboost_only"] = scored["A_xgboost_only"]
        comparisons["B_xgboost_autoencoder"] = scored["B_autoencoder_ranking"]
        limitation = (
            "Graph comparisons C, D, and the hybrid policy E were not scored. "
            "score_graph is a deterministic structuring/mule heuristic, and PaySim "
            "has no labels for those patterns. The autoencoder operating point was "
            "not refit: its saved percentile used this test slice, so only threshold-free "
            "ranking is reported. These figures are synthetic PaySim, not UPI validation, "
            "and they do not show that fusion improves detection."
        )
    return {
        "paysim_csv": paysim,
        "upi_csv": UPI.is_file(),
        "test_rows": None if scored is None else scored["test_rows"],
        "test_fraud": None if scored is None else scored["test_fraud"],
        "comparisons": comparisons,
        "latency": _latency(),
        "limitation": limitation,
    }


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
