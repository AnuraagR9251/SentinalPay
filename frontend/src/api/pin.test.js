import assert from 'node:assert/strict';
import { test } from 'node:test';

import { pinFeedback } from './pin.js';

test('wrong pin is Incorrect OTP and does not fail payment yet', () => {
  assert.deepEqual(pinFeedback({ ok: false, error: 'invalid_pin' }), {
    ok: false,
    message: 'Incorrect OTP',
    failPayment: false,
  });
});

test('locked pin fails the payment', () => {
  const out = pinFeedback({ ok: false, error: 'locked' });
  assert.equal(out.ok, false);
  assert.equal(out.failPayment, true);
  assert.match(out.message, /3 incorrect OTP/i);
});

test('boolean true still counts as success', () => {
  assert.equal(pinFeedback(true).ok, true);
});
