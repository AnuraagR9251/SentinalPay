export const SECONDARY_COPY = {
  APPROVE: 'Security checks passed. Continue to payment.',
  REJECT: 'Transaction rejected following automated security assessment.',
  CONTINUE_HOLD: 'Transaction remains pending additional security checks. Payment has not been completed.',
};

export function paymentGate(score) {
  const action = score && (score.action || score.risk_tier);
  const decision = score && score.canonical_decision;
  if (action === 'BLOCK' || decision === 'BLOCK') return 'block';
  if (action === 'STEP_UP') return 'otp';
  if (action === 'HOLD' || decision === 'REVIEW') return 'hold';
  if (action === 'ALLOW' || decision === 'ALLOW') return 'pay';
  return 'block';
}

export function formatDecisionLine({
  canonicalDecision,
  riskTier,
  canonicalRiskScore,
  pXgb,
  mlCalibrated,
} = {}) {
  const score =
    canonicalRiskScore == null || Number.isNaN(Number(canonicalRiskScore))
      ? '—'
      : `${Number(canonicalRiskScore)}/100`;
  const p = pXgb == null || Number.isNaN(Number(pXgb)) ? '—' : Number(pXgb).toFixed(4);
  const cal = mlCalibrated ? 'UPI-calibrated' : 'PaySim uncalibrated';
  return `${canonicalDecision || '—'} → ${riskTier || '—'} · canonical ${score} · P_xgb ${p} (${cal})`;
}
