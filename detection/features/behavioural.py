"""Behavioural features derived from a user's rolling payment history.

Each function documents *why* the signal matters for UPI fraud, not just
how it is computed. All functions are pure: they never mutate `history`.
"""

from __future__ import annotations

from datetime import timedelta
from statistics import mean, pstdev, stdev
from typing import Optional, Sequence

from detection.constants import MIN_HISTORY_FOR_ZSCORE, ZSCORE_SATURATION
from detection.models import Transaction, UserProfile


def amount_zscore(transaction: Transaction, history: Sequence[Transaction]) -> Optional[float]:
    """Signed z-score of the current amount versus the user's history.

    Why: account-takeover and mule accounts typically spike well above a
    victim's established ticket size (rent, groceries, small P2P). A
    statistically large deviation is therefore a strong ATO / drain cue.
    Returns None when history is too short for a meaningful z-score —
    unknown is not treated as guilty.
    """
    amounts = [txn.amount for txn in history]
    if len(amounts) < MIN_HISTORY_FOR_ZSCORE:
        return None
    avg = mean(amounts)
    # Sample stdev with a population fallback when n==1 would be invalid;
    # we already require MIN_HISTORY_FOR_ZSCORE >= 2 in practice (3).
    spread = stdev(amounts) if len(amounts) > 1 else pstdev(amounts)
    if spread == 0.0:
        # A perfectly stable baseline: any different amount is a full
        # saturation event; an identical amount is zero deviation.
        if transaction.amount == avg:
            return 0.0
        return ZSCORE_SATURATION if transaction.amount > avg else -ZSCORE_SATURATION
    return (transaction.amount - avg) / spread


def is_new_payee(
    transaction: Transaction,
    history: Sequence[Transaction],
    profile: UserProfile,
) -> bool:
    """True when the payee has never appeared for this user.

    Why: UPI fraud (ATO, social-engineering, mule cash-out) almost always
    introduces a first-time beneficiary. A new VPA alone is not proof, but
    combined with a spend spike or velocity burst it is highly predictive.
    """
    known = set(profile.known_payees)
    known.update(txn.payee_vpa for txn in history)
    return transaction.payee_vpa not in known


def velocity(
    transaction: Transaction,
    history: Sequence[Transaction],
    window_seconds: float,
) -> int:
    """Count of this user's transactions in the trailing window, including current.

    Why: scripted drain and "card-testing" analogues on UPI fire many
    payments in minutes. A human paying a merchant rarely exceeds a handful
    of distinct transfers in five minutes. The current txn is included so a
    lone payment still has velocity 1 rather than 0.
    """
    window = timedelta(seconds=window_seconds)
    start = transaction.timestamp - window
    prior = sum(1 for txn in history if start <= txn.timestamp <= transaction.timestamp)
    return prior + 1


def seconds_since_last(
    transaction: Transaction,
    history: Sequence[Transaction],
) -> Optional[float]:
    """Elapsed seconds between the previous txn and this one.

    Why: rapid-fire repeats (seconds apart) are characteristic of automated
    account drain. A long gap is normal life. Returns None when the user
    has no prior transaction — a new account, not a replay.
    """
    prior_ts = [txn.timestamp for txn in history if txn.timestamp <= transaction.timestamp]
    if not prior_ts:
        return None
    last = max(prior_ts)
    return (transaction.timestamp - last).total_seconds()
