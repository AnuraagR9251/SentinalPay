const SCORE_API = import.meta.env.VITE_SCORE_API_URL || 'http://localhost:8000';

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
    const err = new Error(body.errors[0].message);
    err.graphql = true;
    throw err;
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

export async function loginViaGraphql(userId, password) {
  const data = await graphql(
    `mutation Login($userId: String!, $password: String!) {
      login(userId: $userId, password: $password) { token userId }
    }`,
    { userId, password }
  );
  return { token: data.login.token, user_id: data.login.userId };
}

export async function verifyPinViaGraphql(pin, headers = {}) {
  const data = await graphql(
    `mutation Pin($pin: String!) { verifyPin(pin: $pin) { ok } }`,
    { pin },
    headers
  );
  return Boolean(data.verifyPin?.ok);
}
