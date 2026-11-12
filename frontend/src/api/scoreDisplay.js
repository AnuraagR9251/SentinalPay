export function paymentGate(score, reviewAsksOtp = false) {
  const tier = score && score.risk_tier;
  const decision = score && score.canonical_decision;
  if (tier === 'BLOCK' || decision === 'BLOCK') return 'block';
  if (tier === 'STEP_UP' || (reviewAsksOtp && (tier === 'HOLD' || decision === 'REVIEW'))) return 'otp';
  if (tier === 'HOLD' || decision === 'REVIEW') return 'hold';
  if (tier === 'ALLOW') return 'pay';
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
