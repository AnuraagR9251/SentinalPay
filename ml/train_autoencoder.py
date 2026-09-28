"""Train a dense autoencoder on legitimate behavioural + location features.

Usage (from repo root):

    python ml/train_autoencoder.py
    py -3 ml/train_autoencoder.py

The encoder is fit on label==0 rows only. Fraud is held out of training
on purpose: reconstruction error is the anomaly signal, not a supervised
class boundary.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from detection.scoring_engine import FEATURE_VECTOR_NAMES  # noqa: E402
from ml.train_xgboost import build_feature_frames, chronological_split  # noqa: E402

logging.basicConfig(level=os.getenv("SENTINALPAY_LOG_LEVEL", "INFO"))
logger = logging.getLogger("sentinalpay.ml.ae")

MODEL_DIR = REPO_ROOT / "ml" / "models"
MODEL_PATH = MODEL_DIR / "autoencoder_model.keras"
THRESHOLD_PATH = MODEL_DIR / "autoencoder_threshold.json"
RANDOM_SEED = 7102
EPOCHS = 40
BATCH_SIZE = 64


def _matrix(frame: pd.DataFrame) -> np.ndarray:
    return frame[list(FEATURE_VECTOR_NAMES)].to_numpy(dtype=np.float32)


def _reconstruction_error(model, matrix: np.ndarray) -> np.ndarray:
    predicted = model.predict(matrix, verbose=0)
    return np.mean(np.square(matrix - predicted), axis=1)


def _build_model(input_dim: int):
    from tensorflow import keras
    from tensorflow.keras import layers

    model = keras.Sequential(
        [
            layers.Input(shape=(input_dim,)),
            layers.Dense(16, activation="relu"),
            layers.Dense(8, activation="relu"),
            layers.Dense(16, activation="relu"),
            layers.Dense(input_dim, activation="linear"),
        ]
    )
    model.compile(optimizer=keras.optimizers.Adam(learning_rate=0.001), loss="mse")
    return model


def train() -> dict[str, float]:
    paysim, upi = build_feature_frames()
    train_df, test_df = chronological_split(paysim)
    if not upi.empty:
        upi_train, upi_test = chronological_split(upi)
        train_df = pd.concat([train_df, upi_train], ignore_index=True)
        test_df = pd.concat([test_df, upi_test], ignore_index=True)

    legit_train = train_df.loc[train_df["_y"] == 0]
    if legit_train.empty:
        raise RuntimeError("no legitimate rows to train the autoencoder")

    x_legit = _matrix(legit_train)
    logger.info("ae train legit=%s (fraud excluded)", len(x_legit))

    np.random.seed(RANDOM_SEED)
    model = _build_model(len(FEATURE_VECTOR_NAMES))
    model.fit(
        x_legit,
        x_legit,
        epochs=EPOCHS,
        batch_size=BATCH_SIZE,
        shuffle=True,
        verbose=2,
    )

    val_legit = test_df.loc[test_df["_y"] == 0]
    val_fraud = test_df.loc[test_df["_y"] == 1]
    if val_legit.empty:
        raise RuntimeError("no legitimate rows in the held-out set for a threshold")

    errors_legit = _reconstruction_error(model, _matrix(val_legit))
    threshold = float(np.percentile(errors_legit, 95))
    if threshold <= 0:
        threshold = float(np.nextafter(0.0, 1.0))

    # Not precision/recall: this is an unsupervised reconstruction-error
    # flag. "Anomalous" means error >= 95th percentile of *legit* holdout
    # error, not a trained class decision. A flagged legit row is a
    # reconstruction outlier, not a false positive in the classifier sense.
    flagged_legit = int(np.sum(errors_legit >= threshold))
    flagged_fraud = 0
    if not val_fraud.empty:
        errors_fraud = _reconstruction_error(model, _matrix(val_fraud))
        flagged_fraud = int(np.sum(errors_fraud >= threshold))

    print(f"anomaly_threshold={threshold:.6f}")
    print(f"val_legit={len(val_legit)} flagged_anomalous={flagged_legit}")
    print(f"val_fraud={len(val_fraud)} flagged_anomalous={flagged_fraud}")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model.save(MODEL_PATH)
    THRESHOLD_PATH.write_text(
        json.dumps(
            {
                "threshold": threshold,
                "percentile": 95,
                "feature_names": list(FEATURE_VECTOR_NAMES),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"saved model -> {MODEL_PATH}")
    print(f"saved threshold -> {THRESHOLD_PATH}")
    return {"threshold": threshold, "flagged_legit": flagged_legit, "flagged_fraud": flagged_fraud}


if __name__ == "__main__":
    train()
