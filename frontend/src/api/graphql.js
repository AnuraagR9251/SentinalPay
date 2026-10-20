import { graphqlFailure } from './http.js';

const SCORE_API = import.meta.env?.VITE_SCORE_API_URL || 'http://localhost:8000';

const SCORE_FIELDS = `
  transactionId
  riskScore
  riskTier
  pXgb
  pAe
  pGraph
  pHybrid
  structuringFlag
  aeAvailable
  graphAvailable
  structuringAvailable
  actionRequired
  canonicalDecision
  canonicalRiskScore
  action
  mlAvailable
  challengeId
  challengeKind
  challengeNote
  modelProbability
  reasonCodes
  policyVersion
  inferenceLatencyMs
  mlCalibratedForUpi
  mlEvaluation
  scoreComponents
  topContributingFeatures { name value }
  contributions { name value }
`;

function toRestShape(node) {
  if (!node) return null;
  return {
    transaction_id: node.transactionId,
    risk_score: node.riskScore,
    risk_tier: node.riskTier,
    P_xgb: node.pXgb,
    P_ae: node.pAe,
    P_graph: node.pGraph,
    P_hybrid: node.pHybrid,
    structuring_flag: node.structuringFlag,
    ae_available: Boolean(node.aeAvailable),
    graph_available: Boolean(node.graphAvailable),
    structuring_available: Boolean(node.structuringAvailable),
    action_required: node.actionRequired,
    canonical_decision: node.canonicalDecision,
    canonical_risk_score: node.canonicalRiskScore,
    action: node.action,
    ml_available: node.mlAvailable,
    challenge_id: node.challengeId || null,
    challenge_kind: node.challengeKind || null,
    challenge_note: node.challengeNote || null,
    model_probability: node.modelProbability,
    reason_codes: node.reasonCodes || [],
    policy_version: node.policyVersion || null,
    inference_latency_ms: node.inferenceLatencyMs,
    ml_calibrated_for_upi: node.mlCalibratedForUpi,
    ml_evaluation: node.mlEvaluation || null,
    score_components: node.scoreComponents || null,
    top_contributing_features: node.topContributingFeatures || [],
    contributions: node.contributions || []
  };
}

export async function graphql(query, variables, headers = {}) {
  const response = await fetch(`${SCORE_API}/graphql`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify({ query, variables })
  });
  const body = await response.json();
  if (body.errors?.length) {
    throw graphqlFailure(body);
  }
  return body.data;
}

export async function scoreViaGraphql(input, headers = {}) {
  const data = await graphql(
    `mutation Score($input: ScoreInput!) {
      scoreTransaction(input: $input) { ${SCORE_FIELDS} }
    }`,
    { input },
    headers
  );
  return toRestShape(data.scoreTransaction);
}

function evaluateInput(row) {
  const input = {
    userId: row.userId,
    amount: row.amount,
    currency: row.currency || 'INR',
    merchantId: row.merchantId,
    merchantCategory: row.merchantCategory || null,
    transactionId: row.transactionId,
    timestamp: row.timestamp,
    deviceId: row.deviceId || null,
  };
  if (row.latitude != null && row.longitude != null) {
    input.latitude = row.latitude;
    input.longitude = row.longitude;
  }
  return input;
}

export function shapeEvaluateResult(node) {
  const payload = node?.payload && typeof node.payload === 'object' ? node.payload : {};
  const ml = payload.ml && typeof payload.ml === 'object' ? payload.ml : {};
  const exp = payload.experimental && typeof payload.experimental === 'object' ? payload.experimental : {};
  const rules = payload.rules && typeof payload.rules === 'object' ? payload.rules : { triggered_rules: [] };
  return {
    transaction_id: node.transactionId,
    user_id: node.userId,
    canonical_decision: node.decision,
    canonical_risk_score: node.riskScore,
    risk_tier: node.action === 'STEP_UP' ? 'STEP_UP' : node.decision === 'BLOCK' ? 'BLOCK' : node.decision === 'ALLOW' ? 'ALLOW' : 'HOLD',
    action: node.action,
    location_baseline: node.locationBaseline || payload.location_baseline || null,
    ml_available: node.modelAvailable ?? ml.available ?? null,
    P_xgb: ml.available ? ml.fraud_probability : null,
    ml_calibrated_for_upi: ml.calibrated_for_upi ?? false,
    ml_evaluation: ml.evaluation || null,
    reason_codes: node.reasonCodes || payload.reason_codes || [],
    policy_version: node.policyVersion || payload.policy_version || null,
    rules,
    behavior: payload.behavior || { anomalies: [] },
    components: payload.components || null,
    experimental: {
      ...exp,
      note: exp.note || 'experimental; not blended into canonical ALLOW/REVIEW/BLOCK',
    },
    P_ae: exp.ae_available ? exp.P_ae : null,
    P_graph: exp.graph_available ? exp.P_graph : null,
    structuring_flag: exp.structuring_flag ?? null,
    ae_available: Boolean(exp.ae_available),
    graph_available: Boolean(exp.graph_available),
    idempotent: Boolean(payload.idempotent),
    payload,
  };
}

export async function evaluateViaGraphql(row, headers = {}) {
  const data = await graphql(
    `mutation Eval($input: EvaluateInput!) {
      evaluateTransaction(input: $input) {
        transactionId
        userId
        riskScore
        decision
        action
        locationBaseline
        modelAvailable
        reasonCodes
        policyVersion
        payload
      }
    }`,
    { input: evaluateInput(row) },
    headers
  );
  return shapeEvaluateResult(data.evaluateTransaction);
}

export { logoutViaRest } from './session.js';

export async function loginViaGraphql(userId, password) {
  const data = await graphql(
    `mutation Login($userId: String!, $password: String!) {
      login(userId: $userId, password: $password) { token userId }
    }`,
    { userId, password }
  );
  return { token: data.login.token, user_id: data.login.userId };
}

export async function verifyPinViaGraphql(pin, headers = {}, challengeId = null) {
  try {
    const data = await graphql(
      `mutation Pin($pin: String!, $challengeId: String) {
        verifyPin(pin: $pin, challengeId: $challengeId) { ok note error }
      }`,
      { pin, challengeId: challengeId || null },
      headers
    );
    const node = data.verifyPin || {};
    return { ok: Boolean(node.ok), error: node.error || '' };
  } catch (err) {
    const msg = String((err && err.message) || '').toLowerCase();
    if (err?.rateLimited || msg.includes('too many pin') || msg.includes('locked')) {
      return { ok: false, error: 'locked' };
    }
    return { ok: false, error: 'invalid_pin' };
  }
}
