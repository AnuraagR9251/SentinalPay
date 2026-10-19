import assert from 'node:assert/strict';
import { test } from 'node:test';

import { graphqlFailure, retryDelayMs } from './http.js';

test('retry-after seconds become a delay; missing uses fallback', () => {
  assert.equal(retryDelayMs('8'), 8000);
  assert.equal(retryDelayMs('60'), 60000);
  assert.equal(retryDelayMs('', 5000), 5000);
  assert.equal(retryDelayMs('nope', 9000), 9000);
});

test('graphql 429 extensions are rate-limited, not a generic failure', () => {
  const err = graphqlFailure({
    errors: [{ message: 'too many requests', extensions: { httpStatus: 429, code: 429 } }],
  });
  assert.equal(err.rateLimited, true);
  assert.equal(err.httpStatus, 429);
  assert.equal(err.graphql, true);
  assert.equal(err.message, 'too many requests');
});

test('graphql 401 is not treated as rate limited', () => {
  const err = graphqlFailure({
    errors: [{ message: 'login required', extensions: { httpStatus: 401 } }],
  });
  assert.equal(err.rateLimited, false);
  assert.equal(err.httpStatus, 401);
});
