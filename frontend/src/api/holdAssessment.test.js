import assert from 'node:assert/strict';
import { test } from 'node:test';

import { holdView, mayMutateBalance, remainingSeconds } from './holdAssessment.js';

test('countdown starts at 15 seconds from the server deadline', () => {
  const start = Date.parse('2026-11-13T00:00:00Z');
  const deadline = new Date(start + 15000).toISOString();
  assert.equal(remainingSeconds(deadline, start), 15);
});

test('countdown keeps the original deadline across later reads', () => {
  const start = Date.parse('2026-11-13T00:00:00Z');
  const deadline = new Date(start + 15000).toISOString();
  assert.equal(remainingSeconds(deadline, start + 4000), 11);
  assert.equal(remainingSeconds(deadline, start + 4000), 11);
  assert.equal(remainingSeconds(deadline, start + 15000), 0);
});

test('a local timeout does not approve', () => {
  const view = holdView({ outcome: 'PENDING', deadline: '2026-11-13T00:00:15Z' });
  assert.equal(view.phase, 'hold');
  assert.equal(remainingSeconds(view.deadline, Date.parse('2026-11-13T00:00:15Z')), 0);
  assert.notEqual(view.phase, 'cleared');
});

test('ALLOW and DECLINE render as terminal phases', () => {
  assert.equal(holdView({ outcome: 'ALLOW', risk_score: 44, decision: 'REVIEW' }).phase, 'cleared');
  assert.equal(holdView({ outcome: 'DECLINE' }).phase, 'block');
  assert.equal(holdView({ outcome: 'EXPIRED' }).phase, 'block');
});

test('an unreadable assessment fails closed', () => {
  assert.equal(holdView({}).phase, 'error');
  assert.equal(holdView({ outcome: 'APPROVE' }).phase, 'error');
});

test('balance changes only after verified settlement', () => {
  assert.equal(mayMutateBalance(false), false);
  assert.equal(mayMutateBalance(undefined), false);
  assert.equal(mayMutateBalance(true), true);
});
