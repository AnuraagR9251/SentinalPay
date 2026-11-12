import assert from 'node:assert/strict';
import { test } from 'node:test';

import { holdContinueReady, holdView, mayMutateBalance, remainingSeconds } from './holdAssessment.js';

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

test('the orange timer finishes before Continue, and a decline does not continue', () => {
  const start = Date.parse('2026-11-13T00:00:00Z');
  const deadline = '2026-11-13T00:00:15Z';
  const allowed = holdView({ outcome: 'ALLOW', deadline, risk_score: 55, decision: 'REVIEW' });
  assert.equal(allowed.phase, 'hold');
  assert.equal(holdContinueReady(allowed, start), false);
  assert.equal(holdContinueReady(allowed, start + 15000), true);
  const declined = holdView({ outcome: 'DECLINE', deadline });
  assert.equal(declined.phase, 'hold');
  assert.equal(holdContinueReady(declined, start + 15000), false);
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
