export const SECONDARY_COPY = {
  ALLOW: 'Security checks passed. Continue to payment.',
  DECLINE: 'Transaction declined following automated security assessment.',
  EXPIRED: 'The security assessment expired. Payment was not completed.',
  PENDING: 'Pending security assessment. Payment has not been completed.',
};

export function paymentGate(score) {
  const action = score && score.action;
  if (action === 'BLOCK') return 'block';
  if (action === 'STEP_UP') return 'otp';
  if (action === 'HOLD') return 'hold';
  if (action === 'ALLOW') return 'pay';
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
