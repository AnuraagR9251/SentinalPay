import assert from 'node:assert/strict';
import { test } from 'node:test';

import { UPI_MAX_RUPEES, attemptKey, claimAttempt, releaseAttempt, withinUpiLimit } from './paymentAttempt.js';

const fields = {
  userId: 'aarav@senitenial',
  amount: 200,
  merchantId: 'priya.p@oksbi',
  deviceId: 'phone-1',
  latitude: 12.9716,
  longitude: 77.5946,
};

test('UPI payments stop at 5 digits', () => {
  assert.equal(UPI_MAX_RUPEES, 99999);
  assert.equal(withinUpiLimit(99999), true);
  assert.equal(withinUpiLimit(100000), false);
  assert.equal(withinUpiLimit(0), false);
});

test('a retry reuses the payment id and timestamp', () => {
  const cache = {};
  const key = attemptKey(fields);
  const first = claimAttempt(cache, key, 1000);
  const second = claimAttempt(cache, key, 9999);
  assert.equal(second.transactionId, 'tx-1000');
  assert.equal(second.timestamp, first.timestamp);
  assert.equal(second.transactionId.startsWith('lab-'), false);
});

test('a different amount is a different payment', () => {
  const cache = {};
  const first = claimAttempt(cache, attemptKey(fields), 1000);
  const second = claimAttempt(cache, attemptKey({ ...fields, amount: 500 }), 2000);
  assert.notEqual(first.transactionId, second.transactionId);
});

test('a completed payment can be sent again as a new id', () => {
  const cache = {};
  const key = attemptKey(fields);
  claimAttempt(cache, key, 1000);
  releaseAttempt(cache, key);
  const again = claimAttempt(cache, key, 3000);
  assert.equal(again.transactionId, 'tx-3000');
});
