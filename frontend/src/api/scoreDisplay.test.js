import assert from 'node:assert/strict';
import { test } from 'node:test';

import { SECONDARY_COPY, formatDecisionLine, paymentGate } from './scoreDisplay.js';

test('secondary outcomes use the automated messages', () => {
  assert.equal(SECONDARY_COPY.APPROVE, 'Security checks passed. Continue to payment.');
  assert.equal(SECONDARY_COPY.REJECT, 'Transaction rejected following automated security assessment.');
  assert.equal(
    SECONDARY_COPY.CONTINUE_HOLD,
    'Transaction remains pending additional security checks. Payment has not been completed.',
  );
});

test('hold stays held and only step-up asks for the existing challenge', () => {
  assert.equal(paymentGate({ action: 'ALLOW', canonical_decision: 'ALLOW' }), 'pay');
  assert.equal(paymentGate({ action: 'HOLD', risk_tier: 'HOLD', canonical_decision: 'REVIEW' }), 'hold');
  assert.equal(paymentGate({ action: 'BLOCK', canonical_decision: 'BLOCK' }), 'block');
  assert.equal(paymentGate({ action: 'STEP_UP', risk_tier: 'STEP_UP', canonical_decision: 'REVIEW' }), 'otp');
});

test('does not present a 0-1 display score as P_xgb', () => {
  const line = formatDecisionLine({
    canonicalDecision: 'REVIEW',
    riskTier: 'HOLD',
    canonicalRiskScore: 44,
    pXgb: 0.9996,
    mlCalibrated: false,
  });
  assert.match(line, /canonical 44\/100/);
  assert.match(line, /P_xgb 0\.9996/);
  assert.match(line, /PaySim uncalibrated/);
  assert.equal(line.includes('0.440'), false);
  assert.equal(line.includes('UPI-calibrated'), false);
});

test('does not call a missing P_xgb a validated UPI probability', () => {
  const line = formatDecisionLine({
    canonicalDecision: 'REVIEW',
    riskTier: 'HOLD',
    canonicalRiskScore: 20,
    pXgb: null,
    mlCalibrated: false,
  });
  assert.match(line, /P_xgb —/);
  assert.match(line, /PaySim uncalibrated/);
  assert.equal(line.includes('UPI-calibrated'), false);
});
