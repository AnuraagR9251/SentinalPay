"""Configurable thresholds and aggregation weights. Change env, not code."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    return float(raw) if raw else default


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else default


def _csv(name: str, default: tuple[str, ...]) -> frozenset[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return frozenset(default)
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


@dataclass(frozen=True)
class RiskConfig:
    weight_rules: float = 0.25
    weight_behavior: float = 0.25
    weight_ml: float = 0.40
    weight_security: float = 0.10
    allow_max: float = 30.0
    review_max: float = 70.0
    velocity_5m_limit: int = 5
    velocity_1h_limit: int = 12
    amount_z_flag: float = 3.0
    geo_speed_kmh: float = 800.0
    device_user_cap: int = 4
    rate_limit_per_min: int = 40
    replay_seconds: float = 15.0
    high_risk_categories: frozenset[str] = frozenset(("gambling", "crypto", "jewelry"))
    engine_version: str = "sentinelpay_v1"

    @classmethod
    def load(cls) -> RiskConfig:
        cfg = cls(
            weight_rules=_float("SENTINALPAY_WEIGHT_RULES", 0.25),
            weight_behavior=_float("SENTINALPAY_WEIGHT_BEHAVIOR", 0.25),
            weight_ml=_float("SENTINALPAY_WEIGHT_ML", 0.40),
            weight_security=_float("SENTINALPAY_WEIGHT_SECURITY", 0.10),
            allow_max=_float("SENTINALPAY_DECIDE_ALLOW_MAX", 30.0),
            review_max=_float("SENTINALPAY_DECIDE_REVIEW_MAX", 70.0),
            velocity_5m_limit=_int("SENTINALPAY_RULE_VELOCITY_5M", 5),
            velocity_1h_limit=_int("SENTINALPAY_RULE_VELOCITY_1H", 12),
            amount_z_flag=_float("SENTINALPAY_RULE_AMOUNT_Z", 3.0),
            geo_speed_kmh=_float("SENTINALPAY_RULE_GEO_KMH", 800.0),
            device_user_cap=_int("SENTINALPAY_DEVICE_USER_CAP", 4),
            rate_limit_per_min=_int("SENTINALPAY_RATE_LIMIT_PER_MIN", 40),
            replay_seconds=_float("SENTINALPAY_REPLAY_SECONDS", 15.0),
            high_risk_categories=_csv(
                "SENTINALPAY_HIGH_RISK_CATEGORIES",
                ("gambling", "crypto", "jewelry"),
            ),
        )
        total = cfg.weight_rules + cfg.weight_behavior + cfg.weight_ml + cfg.weight_security
        if abs(total - 1.0) > 1e-6:
            raise RuntimeError(f"risk weights must sum to 1.0, got {total}")
        if not (0.0 <= cfg.allow_max < cfg.review_max <= 100.0):
            raise RuntimeError("decision cutovers must be 0 <= allow_max < review_max <= 100")
        return cfg
