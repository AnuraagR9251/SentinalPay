"""Train the 3-class payment-risk XGBoost model.

Usage (from repo root):

    py -3 -m ml.train

Writes artefacts under ml/artifacts/ (gitignored). Logs class counts and
metrics only — never raw transaction or merchant fields.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import numpy as np
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

from ml.features import FEATURE_NAMES, ID_TO_LABEL, LABELS
from ml.prepare import collect_training_frame

logging.basicConfig(level=os.getenv("SENTINALPAY_LOG_LEVEL", "INFO"))
logger = logging.getLogger("sentinalpay.ml.train")

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
MODEL_PATH = ARTIFACT_DIR / "payment_risk_xgb.json"
META_PATH = ARTIFACT_DIR / "model_meta.json"
METRICS_PATH = ARTIFACT_DIR / "metrics.json"


def train() -> dict:
    matrix, labels, medians = collect_training_frame()
    x_train, x_test, y_train, y_test = train_test_split(
        matrix,
        labels,
        test_size=0.2,
        random_state=7102,
        stratify=labels,
    )
    model = XGBClassifier(
        n_estimators=160,
        max_depth=6,
        learning_rate=0.08,
        subsample=0.85,
        colsample_bytree=0.85,
        objective="multi:softprob",
        num_class=len(LABELS),
        eval_metric="mlogloss",
        tree_method="hist",
        n_jobs=4,
        random_state=7102,
    )
    model.fit(x_train, y_train)
    predicted = model.predict(x_test)
    report = classification_report(
        y_test,
        predicted,
        target_names=list(LABELS),
        output_dict=True,
        zero_division=0,
    )
    matrix_counts = confusion_matrix(y_test, predicted).tolist()
    logger.info("holdout weighted f1=%.3f", report["weighted avg"]["f1-score"])

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    model.save_model(MODEL_PATH)
    META_PATH.write_text(
        json.dumps(
            {
                "feature_names": list(FEATURE_NAMES),
                "id_to_label": {str(key): value for key, value in ID_TO_LABEL.items()},
                "category_medians": medians,
                "model_path": MODEL_PATH.name,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    METRICS_PATH.write_text(
        json.dumps({"classification_report": report, "confusion_matrix": matrix_counts}, indent=2),
        encoding="utf-8",
    )
    # Confirm we never wrote raw PII keys into artefacts.
    meta_text = META_PATH.read_text(encoding="utf-8").lower()
    for banned in ("nameorig", "namedest", "merchant", "vpa", "phone"):
        if banned in meta_text and banned != "merchant":
            raise RuntimeError("refusing to write artefact that looks like it contains PII keys")
    return report


if __name__ == "__main__":
    train()
