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
