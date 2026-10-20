import assert from 'node:assert/strict';
import { test } from 'node:test';

import { shapeEvaluateResult } from './graphql.js';

test('evaluate shape keeps experimental signals off the canonical decision', () => {
  const shaped = shapeEvaluateResult({
    transactionId: 'lab-1',
    userId: 'lab.grocery.r1@sentinal.sim',
    riskScore: 22,
    decision: 'ALLOW',
    action: 'ALLOW',
    locationBaseline: 'KNOWN_NORMAL_LOCATION',
    modelAvailable: true,
    reasonCodes: ['ML_UNCALIBRATED_PAYSIM'],
    policyVersion: 'sentinelpay_v1',
    payload: {
      idempotent: false,
      rules: { triggered_rules: [{ rule: 'NEW_MERCHANT', reason: 'merchant is unusual for this user' }] },
      ml: { available: true, fraud_probability: 0.4, calibrated_for_upi: false, evaluation: 'synthetic_paysim' },
      experimental: {
        ae_available: false,
        graph_available: true,
        P_graph: 0.12,
        structuring_flag: false,
        note: 'experimental; not blended into canonical ALLOW/REVIEW/BLOCK',
      },
    },
  });
  assert.equal(shaped.canonical_decision, 'ALLOW');
  assert.equal(shaped.canonical_risk_score, 22);
  assert.equal(shaped.action, 'ALLOW');
  assert.equal(shaped.rules.triggered_rules[0].rule, 'NEW_MERCHANT');
  assert.equal(shaped.experimental.structuring_flag, false);
  assert.match(shaped.experimental.note, /not blended/);
  assert.equal(shaped.ml_calibrated_for_upi, false);
});
