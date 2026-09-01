"""SentinalPay detection package.

Public surface is deliberately small: callers (dashboard, future FastAPI
layer) should import only from here, never from `detection.features`.
"""

from detection.models import PaymentRiskLabel, RiskAssessment, RiskTier
from detection.scoring_engine import score_transaction
from detection.validation import ScoringValidationError

__all__ = [
    "PaymentRiskLabel",
    "RiskAssessment",
    "RiskTier",
    "ScoringValidationError",
    "score_transaction",
]
