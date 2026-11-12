import test from 'node:test';
import assert from 'node:assert/strict';

import { checkoutOptions, rupeesToPaise } from './razorpayCheckout.js';

test('checkout hides contact and uses the sandbox payer', () => {
  const options = checkoutOptions({
    key: 'rzp_test_example',
    order: { order_id: 'order_1', amount: 100, currency: 'INR' },
  });
  assert.equal(options.prefill.contact, '9000090000');
  assert.equal(options.hidden.email, true);
  assert.equal(options.hidden.contact, true);
  assert.equal(options.method.card, true);
  assert.match(options.description, /4100280000001007/);
  assert.equal(options.method.upi, false);
});

test('rupees become paise and reject under 100 paise', () => {
  assert.equal(rupeesToPaise(1), 100);
  assert.equal(rupeesToPaise(10.5), 1050);
  assert.equal(rupeesToPaise(0.5), null);
  assert.equal(rupeesToPaise(0), null);
  assert.equal(rupeesToPaise('nope'), null);
});
