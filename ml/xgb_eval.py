"""Evaluation helpers for the PaySim XGBoost trainer.

Splits, operating points, and metrics live here so training can be compared
without touching live inference or the committed xgb_v3 pickle.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.isotonic import IsotonicRegression


def prevalence(y: np.ndarray) -> dict[str, float | int]:
    y = np.asarray(y, dtype=np.int32)
    n = int(y.size)
    n_fraud = int(np.sum(y == 1))
    n_legit = int(np.sum(y == 0))
    return {
        "n": n,
        "n_fraud": n_fraud,
        "n_legit": n_legit,
        "fraud_rate": (n_fraud / n) if n else 0.0,
    }


def split_report(name: str, frame: pd.DataFrame) -> dict[str, Any]:
    y = frame["_y"].to_numpy(dtype=np.int32)
    out: dict[str, Any] = {"split": name, **prevalence(y)}
    if "_ts" in frame.columns and len(frame):
        out["ts_min"] = str(frame["_ts"].min())
        out["ts_max"] = str(frame["_ts"].max())
    if "_user" in frame.columns:
        out["n_users"] = int(frame["_user"].nunique())
    unusual = bool(out["n"] >= 20 and (out["fraud_rate"] >= 0.5 or out["fraud_rate"] <= 0.01))
    out["unusual_prevalence"] = unusual
    return out


def chronological_split(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    ordered = frame.sort_values("_ts", kind="mergesort").reset_index(drop=True)
    cut = int(len(ordered) * 0.8)
    if cut < 1 or cut >= len(ordered):
        raise RuntimeError("not enough rows for an 80/20 chronological split")
    return ordered.iloc[:cut], ordered.iloc[cut:]


def chronological_thirds(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Earlier → train, next → tune, newest → final eval."""
    ordered = frame.sort_values("_ts", kind="mergesort").reset_index(drop=True)
    n = len(ordered)
    a, b = int(n * 0.6), int(n * 0.8)
    if a < 1 or b <= a or b >= n:
        raise RuntimeError("not enough rows for a 60/20/20 chronological split")
    return ordered.iloc[:a], ordered.iloc[a:b], ordered.iloc[b:]


def user_disjoint_thirds(frame: pd.DataFrame, seed: int = 7102) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Unseen-originator split. Not a temporal test — keep it separate."""
    if "_user" not in frame.columns:
        raise RuntimeError("user-disjoint split needs an _user column")
    users = list(dict.fromkeys(frame["_user"].astype(str).tolist()))
    rng = np.random.default_rng(seed)
    rng.shuffle(users)
    n = len(users)
    a, b = int(n * 0.6), int(n * 0.8)
    if a < 1 or b <= a or b >= n:
        raise RuntimeError("not enough users for a 60/20/20 user-disjoint split")
    train_u, val_u, test_u = set(users[:a]), set(users[a:b]), set(users[b:])
    if train_u & val_u or train_u & test_u or val_u & test_u:
        raise RuntimeError("user-disjoint splits overlapped")
    train = frame[frame["_user"].astype(str).isin(train_u)].reset_index(drop=True)
    val = frame[frame["_user"].astype(str).isin(val_u)].reset_index(drop=True)
    test = frame[frame["_user"].astype(str).isin(test_u)].reset_index(drop=True)
    return train, val, test


def temporal_subwindows(frame: pd.DataFrame, n_windows: int = 3) -> list[pd.DataFrame]:
    ordered = frame.sort_values("_ts", kind="mergesort").reset_index(drop=True)
    n = len(ordered)
    if n_windows < 1 or n < n_windows:
        return [ordered]
    sizes = [n // n_windows] * n_windows
    for i in range(n % n_windows):
        sizes[i] += 1
    out: list[pd.DataFrame] = []
    start = 0
    for size in sizes:
        out.append(ordered.iloc[start : start + size].reset_index(drop=True))
        start += size
    return out


def assert_temporal_order(train: pd.DataFrame, val: pd.DataFrame, test: pd.DataFrame) -> None:
    if train["_ts"].max() > val["_ts"].min() or val["_ts"].max() > test["_ts"].min():
        raise RuntimeError("temporal split leaked later rows into an earlier fold")


def leakage_correlations(frame: pd.DataFrame, cols: list[str]) -> dict[str, float]:
    y = frame["_y"].to_numpy(dtype=np.float64)
    out: dict[str, float] = {}
    for col in cols:
        series = frame[col].to_numpy(dtype=np.float64)
        if float(np.std(series)) < 1e-12 or len(np.unique(y)) < 2:
            continue
        out[col] = float(np.corrcoef(series, y)[0, 1])
    return out


def constant_features(frame: pd.DataFrame, cols: list[str], eps: float = 1e-12) -> list[str]:
    dead: list[str] = []
    for col in cols:
        if col not in frame.columns:
            dead.append(col)
            continue
        if float(np.nanstd(frame[col].to_numpy(dtype=np.float64))) < eps:
            dead.append(col)
    return dead


def best_threshold(y_true: np.ndarray, scores: np.ndarray) -> float:
    """F1-max threshold. Call with validation scores only."""
    precision, recall, thresholds = precision_recall_curve(y_true, scores)
    if thresholds.size == 0:
        return 0.5
    f1 = np.zeros(thresholds.size)
    for i, _thresh in enumerate(thresholds):
        f1[i] = 0.0 if precision[i] + recall[i] == 0 else 2 * precision[i] * recall[i] / (precision[i] + recall[i])
    return float(thresholds[int(np.argmax(f1))])


def review_operating_point(y_true: np.ndarray, scores: np.ndarray, review_at: float) -> dict[str, float]:
    flagged = scores >= review_at
    fraud = y_true == 1
    legit = y_true == 0
    caught = int(np.sum(flagged & fraud))
    fraud_n = int(np.sum(fraud))
    legit_n = int(np.sum(legit))
    extra = int(np.sum(flagged & legit))
    return {
        "review_at": float(review_at),
        "fraud_caught": caught,
        "fraud_recall": caught / fraud_n if fraud_n else 0.0,
        "legit_review_rate": extra / legit_n if legit_n else 0.0,
        "precision": caught / int(np.sum(flagged)) if int(np.sum(flagged)) else 0.0,
    }


def recall_at_fpr(y_true: np.ndarray, scores: np.ndarray, fpr_target: float = 0.05) -> dict[str, float]:
    legit = y_true == 0
    fraud = y_true == 1
    legit_n = int(np.sum(legit))
    fraud_n = int(np.sum(fraud))
    best = {"fpr_target": float(fpr_target), "threshold": 1.0, "fpr": 0.0, "recall": 0.0}
    if legit_n == 0 or scores.size == 0:
        return best
    for thresh in np.unique(scores):
        flagged = scores >= thresh
        fpr = float(np.sum(flagged & legit) / legit_n)
        if fpr > fpr_target:
            continue
        rec = float(np.sum(flagged & fraud) / fraud_n) if fraud_n else 0.0
        if rec >= best["recall"]:
            best = {"fpr_target": float(fpr_target), "threshold": float(thresh), "fpr": fpr, "recall": rec}
    return best


def brier_and_reliability(y_true: np.ndarray, scores: np.ndarray, bins: int = 10) -> dict[str, Any]:
    if y_true.size == 0:
        return {"brier": None, "bins": []}
    brier = float(brier_score_loss(y_true, np.clip(scores, 0.0, 1.0)))
    edges = np.linspace(0.0, 1.0, bins + 1)
    rows = []
    for i in range(bins):
        right = scores < edges[i + 1] if i < bins - 1 else scores <= edges[i + 1]
        mask = (scores >= edges[i]) & right
        if not np.any(mask):
            continue
        rows.append(
            {
                "bin_left": float(edges[i]),
                "bin_right": float(edges[i + 1]),
                "mean_predicted": float(np.mean(scores[mask])),
                "mean_actual": float(np.mean(y_true[mask])),
                "n": int(np.sum(mask)),
            }
        )
    return {"brier": brier, "bins": rows}


def pack_clf_metrics(y_true: np.ndarray, scores: np.ndarray, thresh: float) -> dict[str, Any]:
    y_true = np.asarray(y_true, dtype=np.int32)
    scores = np.asarray(scores, dtype=np.float64)
    predicted = (scores >= thresh).astype(np.int32)
    tn, fp, fn, tp = confusion_matrix(y_true, predicted, labels=[0, 1]).ravel()
    legit_n = int(tn + fp)
    return {
        **prevalence(y_true),
        "threshold": float(thresh),
        "precision": float(precision_score(y_true, predicted, zero_division=0)),
        "recall": float(recall_score(y_true, predicted, zero_division=0)),
        "f1": float(f1_score(y_true, predicted, zero_division=0)),
        "average_precision": float(average_precision_score(y_true, scores)) if len(np.unique(y_true)) > 1 else float("nan"),
        "roc_auc": float(roc_auc_score(y_true, scores)) if len(np.unique(y_true)) > 1 else float("nan"),
        "brier": float(brier_score_loss(y_true, np.clip(scores, 0.0, 1.0))) if y_true.size else float("nan"),
        "fpr": float(fp / legit_n) if legit_n else 0.0,
        "confusion": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "recall_at_1pct_fpr": recall_at_fpr(y_true, scores, 0.01),
        "recall_at_5pct_fpr": recall_at_fpr(y_true, scores, 0.05),
        "recall_at_10pct_fpr": recall_at_fpr(y_true, scores, 0.10),
        "review": review_operating_point(y_true, scores, thresh),
        "score_mean": float(np.mean(scores)) if scores.size else float("nan"),
        "score_p50": float(np.median(scores)) if scores.size else float("nan"),
        "score_p90": float(np.quantile(scores, 0.9)) if scores.size else float("nan"),
    }


def calibrate_scores(
    p_val: np.ndarray,
    y_val: np.ndarray,
    p_out: np.ndarray,
    method: str = "sigmoid",
) -> np.ndarray:
    """Map raw scores using validation labels only. Not a UPI calibrator."""
    p_val = np.asarray(p_val, dtype=np.float64).reshape(-1, 1)
    p_out = np.asarray(p_out, dtype=np.float64).reshape(-1, 1)
    y_val = np.asarray(y_val, dtype=np.int32)
    if method == "isotonic":
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        iso.fit(p_val.ravel(), y_val)
        return np.clip(iso.predict(p_out.ravel()), 0.0, 1.0)
    clf = LogisticRegression(max_iter=400)
    clf.fit(p_val, y_val)
    return clf.predict_proba(p_out)[:, 1]


def cyclic_hour_columns(hour_of_day: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """sin/cos of recovered hour. Only meaningful for wall-clock time, not PaySim step."""
    hour = np.clip(np.asarray(hour_of_day, dtype=np.float64) * 23.0, 0.0, 23.0)
    rad = 2.0 * np.pi * hour / 24.0
    return np.sin(rad), np.cos(rad)


PAYSIM_EPOCH = datetime(2017, 1, 1, tzinfo=timezone.utc)
ROW_ID_NOTE = "sha256(user|timestamp_iso|seq)[:16]; raw originator id is not stored"
USER_ANON_NOTE = "sha256('sentinalpay|'+user)[:16]"
THRESHOLD_SELECTION = {
    "operating_point": "argmax F1 on validation scores only; applied unchanged to test",
    "recall_at_k_fpr_same_fold": (
        "On the reported fold, take the score threshold with the highest recall "
        "among those whose empirical FPR is <= k. This is fold-internal, not a "
        "val-selected operating point."
    ),
    "recall_at_k_fpr_val_selected": (
        "Choose the same-fold 1%/5% FPR threshold on validation, then measure "
        "FPR/recall on test at that frozen threshold."
    ),
}


def anonymize_user(user: str) -> str:
    return hashlib.sha256(f"sentinalpay|{user}".encode("utf-8")).hexdigest()[:16]


def stable_row_id(user: str, ts: Any, seq: int) -> str:
    stamp = pd.Timestamp(ts)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")
    raw = f"{user}|{stamp.isoformat()}|{int(seq)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def attach_eval_ids(frame: pd.DataFrame) -> pd.DataFrame:
    """Add anonymized user + row ids. Keeps `_user` in memory for splits only."""
    out = frame.copy()
    users = out["_user"].astype(str)
    if "_seq" in out.columns:
        seq = out["_seq"].astype(int)
    else:
        seq = out.groupby(users, sort=False).cumcount()
    out["_row_id"] = [stable_row_id(u, t, int(s)) for u, t, s in zip(users, out["_ts"], seq)]
    out["_user_anon"] = [anonymize_user(u) for u in users]
    return out


def operating_at(y_true: np.ndarray, scores: np.ndarray, thresh: float) -> dict[str, float]:
    y_true = np.asarray(y_true, dtype=np.int32)
    scores = np.asarray(scores, dtype=np.float64)
    flagged = scores >= thresh
    legit = y_true == 0
    fraud = y_true == 1
    legit_n = int(np.sum(legit))
    fraud_n = int(np.sum(fraud))
    return {
        "threshold": float(thresh),
        "fpr": float(np.sum(flagged & legit) / legit_n) if legit_n else 0.0,
        "recall": float(np.sum(flagged & fraud) / fraud_n) if fraud_n else 0.0,
        "n_flagged": int(np.sum(flagged)),
    }


def recall_at_fpr_from_val(
    y_val: np.ndarray,
    p_val: np.ndarray,
    y_test: np.ndarray,
    p_test: np.ndarray,
    fpr_target: float,
) -> dict[str, float]:
    chosen = recall_at_fpr(y_val, p_val, fpr_target)
    applied = operating_at(y_test, p_test, chosen["threshold"])
    return {
        "fpr_target": float(fpr_target),
        "selection": "validation_max_recall_at_fpr",
        "val_threshold": float(chosen["threshold"]),
        "val_fpr": float(chosen["fpr"]),
        "val_recall": float(chosen["recall"]),
        **applied,
    }


def constant_fraud_metrics(y_true: np.ndarray) -> dict[str, Any]:
    """Always-predict-fraud baseline. F1 = 2p/(1+p) when p = fraud prevalence."""
    y_true = np.asarray(y_true, dtype=np.int32)
    prev = prevalence(y_true)
    p = float(prev["fraud_rate"])
    scores = np.ones(y_true.size, dtype=np.float64)
    packed = pack_clf_metrics(y_true, scores, 0.5)
    packed["f1_closed_form"] = (2.0 * p / (1.0 + p)) if y_true.size else float("nan")
    packed["note"] = (
        "Always predict fraud: precision = prevalence, recall = 1, "
        f"F1 = 2p/(1+p). ROC-AUC is undefined-as-ranking (constant scores)."
    )
    return packed


def bootstrap_ci(
    y_true: np.ndarray,
    scores: np.ndarray,
    fn: Callable[[np.ndarray, np.ndarray], float],
    *,
    n_boot: int = 300,
    seed: int = 7102,
    alpha: float = 0.05,
) -> dict[str, float | int | None]:
    y_true = np.asarray(y_true)
    scores = np.asarray(scores)
    rng = np.random.default_rng(seed)
    n = int(y_true.size)
    stats: list[float] = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        yi, si = y_true[idx], scores[idx]
        try:
            val = float(fn(yi, si))
        except ValueError:
            continue
        if np.isfinite(val):
            stats.append(val)
    if not stats:
        return {"mean": None, "lo": None, "hi": None, "n_boot": 0}
    return {
        "mean": float(np.mean(stats)),
        "lo": float(np.quantile(stats, alpha / 2.0)),
        "hi": float(np.quantile(stats, 1.0 - alpha / 2.0)),
        "n_boot": len(stats),
    }


def ranking_intervals(y_true: np.ndarray, scores: np.ndarray, *, n_boot: int = 300, seed: int = 7102) -> dict[str, Any]:
    def _auc(y: np.ndarray, s: np.ndarray) -> float:
        if len(np.unique(y)) < 2:
            raise ValueError("one class")
        return float(roc_auc_score(y, s))

    def _ap(y: np.ndarray, s: np.ndarray) -> float:
        if len(np.unique(y)) < 2:
            raise ValueError("one class")
        return float(average_precision_score(y, s))

    def _brier(y: np.ndarray, s: np.ndarray) -> float:
        return float(brier_score_loss(y, np.clip(s, 0.0, 1.0)))

    return {
        "method": "percentile bootstrap, rows resampled with replacement",
        "n_boot_requested": n_boot,
        "seed": seed,
        "roc_auc": bootstrap_ci(y_true, scores, _auc, n_boot=n_boot, seed=seed),
        "average_precision": bootstrap_ci(y_true, scores, _ap, n_boot=n_boot, seed=seed),
        "brier": bootstrap_ci(y_true, scores, _brier, n_boot=n_boot, seed=seed),
    }


def prediction_table(
    split_frames: Mapping[str, pd.DataFrame],
    scores_by_model: Mapping[str, Mapping[str, np.ndarray]],
) -> pd.DataFrame:
    """Wide table: one row per transaction. No raw originator ids."""
    model_names = list(scores_by_model)
    blocks: list[pd.DataFrame] = []
    for split, frame in split_frames.items():
        n = len(frame)
        block = pd.DataFrame(
            {
                "row_id": frame["_row_id"].astype(str).to_numpy() if "_row_id" in frame.columns else [f"{split}:{i}" for i in range(n)],
                "user_anon": frame["_user_anon"].astype(str).to_numpy() if "_user_anon" in frame.columns else [""] * n,
                "timestamp": pd.to_datetime(frame["_ts"], utc=True).astype(str).to_numpy(),
                "y": frame["_y"].to_numpy(dtype=np.int32),
                "split": split,
                "hour_of_day": frame["hour_of_day"].to_numpy(dtype=np.float64) if "hour_of_day" in frame.columns else np.full(n, np.nan),
                "model_variant": ",".join(model_names),
            }
        )
        for name in model_names:
            arr = np.asarray(scores_by_model[name][split], dtype=np.float64)
            if arr.size != n:
                raise RuntimeError(f"{name} {split} scores ({arr.size}) != rows ({n})")
            block[f"score_{name}"] = arr
        blocks.append(block)
    return pd.concat(blocks, ignore_index=True)


def write_prediction_table(path: Path, table: pd.DataFrame) -> None:
    banned = {"_user", "user_id", "nameOrig", "nameDest"}
    present = banned.intersection(set(table.columns))
    if present:
        raise RuntimeError(f"refusing to write raw identity columns: {sorted(present)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(path, index=False)


def feature_export_table(split_frames: Mapping[str, pd.DataFrame], feature_names: list[str]) -> pd.DataFrame:
    blocks: list[pd.DataFrame] = []
    keep = [c for c in feature_names if c]
    for split, frame in split_frames.items():
        cols = {
            "row_id": frame["_row_id"].astype(str) if "_row_id" in frame.columns else pd.RangeIndex(len(frame)).astype(str),
            "user_anon": frame["_user_anon"].astype(str) if "_user_anon" in frame.columns else "",
            "timestamp": pd.to_datetime(frame["_ts"], utc=True).astype(str),
            "y": frame["_y"].astype(np.int32),
            "split": split,
        }
        out = pd.DataFrame(cols)
        for name in keep:
            if name in frame.columns:
                out[name] = frame[name].to_numpy(dtype=np.float64)
        blocks.append(out)
    return pd.concat(blocks, ignore_index=True)


def hour_of_day_analysis(
    splits: Mapping[str, pd.DataFrame],
    *,
    epoch: datetime = PAYSIM_EPOCH,
    windows_a: list[dict[str, Any]] | None = None,
    windows_b: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """PaySim step-hour vs label. Not a UPI circadian analysis."""
    by_split: dict[str, Any] = {}
    hour_rates: list[dict[str, Any]] = []
    for name, frame in splits.items():
        ts = pd.to_datetime(frame["_ts"], utc=True)
        y = frame["_y"].to_numpy(dtype=np.float64)
        hour = ts.dt.hour.to_numpy(dtype=np.float64)
        step = (ts - pd.Timestamp(epoch)).dt.total_seconds().to_numpy(dtype=np.float64) / 3600.0
        hod = frame["hour_of_day"].to_numpy(dtype=np.float64) if "hour_of_day" in frame.columns else hour / 23.0
        recon = hour / 23.0
        row: dict[str, Any] = {
            **prevalence(frame["_y"].to_numpy(dtype=np.int32)),
            "corr_hour_of_day_label": float(np.corrcoef(hod, y)[0, 1]) if len(np.unique(y)) > 1 and float(np.std(hod)) > 0 else None,
            "corr_clock_hour_label": float(np.corrcoef(hour, y)[0, 1]) if len(np.unique(y)) > 1 and float(np.std(hour)) > 0 else None,
            "corr_step_hours_label": float(np.corrcoef(step, y)[0, 1]) if len(np.unique(y)) > 1 and float(np.std(step)) > 0 else None,
            "max_abs_hour_of_day_vs_clock_over_23": float(np.max(np.abs(hod - recon))) if hod.size else None,
            "hour_mean_fraud": float(np.mean(hour[y == 1])) if np.any(y == 1) else None,
            "hour_mean_legit": float(np.mean(hour[y == 0])) if np.any(y == 0) else None,
            "step_mean_fraud": float(np.mean(step[y == 1])) if np.any(y == 1) else None,
            "step_mean_legit": float(np.mean(step[y == 0])) if np.any(y == 0) else None,
        }
        by_split[name] = row
        for h in range(24):
            mask = hour == h
            if not np.any(mask):
                continue
            hour_rates.append(
                {
                    "split": name,
                    "clock_hour": h,
                    "n": int(np.sum(mask)),
                    "n_fraud": int(np.sum((y == 1) & mask)),
                    "fraud_rate": float(np.mean(y[mask])),
                }
            )
    return {
        "evaluation": "synthetic_paysim",
        "calibrated_for_upi": False,
        "definition": "engineer_features sets hour_of_day = timestamp.hour / 23.0",
        "paysim_timestamp": "PAYSIM_EPOCH (2017-01-01 UTC) + step hours, so clock hour = step % 24",
        "splits": by_split,
        "fraud_rate_by_clock_hour": hour_rates,
        "test_windows_A_keep_hour": windows_a,
        "test_windows_B_drop_hour": windows_b,
        "note": (
            "PaySim fraud is generated in simulator time clusters. hour_of_day is a "
            "deterministic function of step, not UPI wall-clock risk. Do not treat "
            "ablation results as UPI feature importance."
        ),
    }
