import { scoreApiRoot } from './session.js';
import { SECONDARY_COPY } from './scoreDisplay.js';

export const ASSESSMENT_SECONDS = 15;

export function remainingSeconds(deadline, now = Date.now()) {
  const end = Date.parse(deadline);
  if (!Number.isFinite(end)) return null;
  return Math.max(0, Math.ceil((end - now) / 1000));
}

export function holdView(row) {
  const outcome = String((row && (row.outcome || row.secondary_outcome)) || '');
  const base = {
    secondaryOutcome: outcome,
    deadline: (row && (row.deadline || row.expires_at)) || null,
    createdAt: (row && row.created_at) || null,
    reasons: (row && row.reasons) || [],
    canonicalDecision: (row && (row.decision || row.canonicalDecision)) || null,
    canonicalRiskScore: row && (row.risk_score ?? row.canonicalRiskScore),
    riskTier: 'HOLD',
  };
  if (base.canonicalRiskScore == null) base.canonicalRiskScore = null;
  if (outcome === 'ALLOW' || outcome === 'PENDING' || outcome === 'DECLINE' || outcome === 'EXPIRED') {
    const message = outcome === 'ALLOW'
      ? SECONDARY_COPY.ALLOW
      : outcome === 'DECLINE'
        ? SECONDARY_COPY.DECLINE
        : outcome === 'EXPIRED'
          ? SECONDARY_COPY.EXPIRED
          : SECONDARY_COPY.PENDING;
    return { ...base, phase: 'hold', message };
  }
  return {
    ...base,
    phase: 'error',
    message: 'Security assessment could not be confirmed. Payment was not completed.',
  };
}

export function holdContinueReady(view, now = Date.now()) {
  if (!view || view.secondaryOutcome !== 'ALLOW') return false;
  return remainingSeconds(view.deadline, now) === 0;
}

export function mayMutateBalance(settled) {
  return settled === true;
}

export async function fetchHoldAssessment(transactionId, headers = {}) {
  const root = scoreApiRoot().replace(/\/$/, '');
  const response = await fetch(`${root}/api/hold-assessment/${encodeURIComponent(transactionId)}`, { headers });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error('assessment failed');
    error.body = body;
    throw error;
  }
  return body;
}
