import assert from 'node:assert/strict';
import { test } from 'node:test';

import { formatDecisionLine, paymentGate } from './scoreDisplay.js';

test('razorpay review asks for otp and a block never pays', () => {
  assert.equal(paymentGate({ risk_tier: 'ALLOW', canonical_decision: 'ALLOW' }, true), 'pay');
  assert.equal(paymentGate({ risk_tier: 'HOLD', canonical_decision: 'REVIEW' }, true), 'otp');
  assert.equal(paymentGate({ risk_tier: 'HOLD', canonical_decision: 'REVIEW' }, false), 'hold');
  assert.equal(paymentGate({ risk_tier: 'BLOCK', canonical_decision: 'BLOCK' }, true), 'block');
  assert.equal(paymentGate({ risk_tier: 'STEP_UP', canonical_decision: 'REVIEW' }, false), 'otp');
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
