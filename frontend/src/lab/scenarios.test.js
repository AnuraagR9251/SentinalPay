import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  ENGINE_STRUCTURING_AMOUNT,
  KNOWN_PAYEE,
  LAB_HOME_DEVICE,
  LAB_NEW_DEVICE,
  SCENARIO_DEFS,
  assertHistoryBeforeCandidate,
  belowThresholdUnit,
  buildScenario,
  resolveLabUser,
} from './scenarios.js';
import { runLabScenario } from './runScenario.js';

const NOW = new Date('2026-10-20T12:00:00.000Z');

function built(id, extra = {}) {
  return buildScenario(id, { now: NOW, runId: 'r1', threshold: 50000, ...extra });
}

test('every preset exists and uses unique ids before the live send', () => {
  const seen = new Set();
  for (const def of SCENARIO_DEFS) {
    const scenario = built(def.id);
    assert.equal(scenario.synthetic, true);
    assertHistoryBeforeCandidate(scenario);
    for (const id of scenario.ids) {
      assert.equal(seen.has(id), false, id);
      seen.add(id);
      assert.match(id, /^lab-/);
    }
  }
});

test('open sandbox uses an isolated lab user', () => {
  const scenario = built('grocery');
  assert.equal(scenario.userId, 'lab.grocery.r1@sentinal.sim');
  assert.equal(scenario.isolatedUser, true);
  assert.equal(resolveLabUser({ scenarioId: 'grocery', runId: 'r1' }), 'lab.grocery.r1@sentinal.sim');
});

test('login-required cannot switch user_id without a 403 from evaluateTransaction', () => {
  const scenario = built('grocery', { requireLogin: true, sessionUser: 'aarav@senitenial' });
  assert.equal(scenario.userId, 'aarav@senitenial');
  assert.equal(scenario.isolatedUser, false);
  assert.ok(scenario.limitations.some((line) => line.includes('403')));
});

test('grocery history is the same known payee and device', () => {
  const scenario = built('grocery');
  assert.equal(scenario.history.length, 5);
  assert.ok(scenario.history.every((row) => row.merchantId === KNOWN_PAYEE));
  assert.ok(scenario.history.every((row) => row.deviceId === LAB_HOME_DEVICE));
  assert.equal(scenario.candidate.merchantId, KNOWN_PAYEE);
  assert.equal(scenario.candidate.amount, 240);
});

test('velocity packs four priors inside five minutes', () => {
  const scenario = built('velocity');
  const live = Date.parse(scenario.candidate.timestamp);
  assert.equal(scenario.history.length, 4);
  for (const row of scenario.history) {
    const dt = (live - Date.parse(row.timestamp)) / 1000;
    assert.ok(dt > 0 && dt <= 180);
  }
});

test('location scenario has Bengaluru priors and a Delhi new device', () => {
  const scenario = built('location_device');
  assert.ok(scenario.history.every((row) => row.latitude === 12.9716));
  assert.equal(scenario.candidate.latitude, 28.6139);
  assert.equal(scenario.candidate.deviceId, LAB_NEW_DEVICE);
  assert.notEqual(scenario.candidate.deviceId, scenario.history[0].deviceId);
});

test('below-threshold units stay under the demo cap and sum over it', () => {
  const scenario = built('below_threshold', { threshold: 2000 });
  const unit = belowThresholdUnit(2000);
  assert.equal(unit, 666);
  assert.ok(scenario.history.every((row) => row.amount < 2000));
  assert.ok(scenario.candidate.amount < 2000);
  assert.equal(scenario.combinedBelowThreshold, unit * 4);
  assert.ok(scenario.combinedBelowThreshold > 2000);
  assert.ok(scenario.combinedBelowThreshold < ENGINE_STRUCTURING_AMOUNT);
  assert.ok(scenario.limitations.some((line) => line.includes('structuring_flag')));
});

test('new payee amount is far above the synthetic baseline', () => {
  const scenario = built('new_payee');
  const avg = scenario.history.reduce((sum, row) => sum + row.amount, 0) / scenario.history.length;
  assert.equal(avg, 200);
  assert.ok(scenario.candidate.amount >= avg * 10);
  assert.ok(!scenario.history.some((row) => row.merchantId === scenario.candidate.merchantId));
});

test('missing location omits coordinates; thin history has one prior', () => {
  const missing = built('missing_location');
  assert.equal(missing.history.every((row) => row.latitude == null), true);
  assert.equal(missing.candidate.latitude, undefined);
  const thin = built('thin_history');
  assert.equal(thin.history.length, 1);
});

test('legit high-frequency stays at three events in five minutes', () => {
  const scenario = built('legit_high_freq');
  assert.equal(scenario.history.length, 2);
  const live = Date.parse(scenario.candidate.timestamp);
  assert.ok(scenario.history.every((row) => (live - Date.parse(row.timestamp)) / 1000 <= 90));
});

test('runLabScenario submits history then the live send through the API helper', async () => {
  const calls = [];
  const fake = async (row) => {
    calls.push(row.transactionId);
    return { transaction_id: row.transactionId, canonical_decision: 'ALLOW' };
  };
  const out = await runLabScenario('replay', { now: NOW, runId: 'api1', submit: fake });
  assert.deepEqual(calls, ['lab-rep-h0-api1', 'lab-rep-live-api1', 'lab-rep-live-api1']);
  assert.equal(out.replay.transaction_id, 'lab-rep-live-api1');
  assert.equal(out.scenario.history.every((row) => Date.parse(row.timestamp) < Date.parse(out.scenario.candidate.timestamp)), true);
});
