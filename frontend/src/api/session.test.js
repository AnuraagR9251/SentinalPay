import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  LOCAL_SESSION_UNCONFIRMED,
  SESSION_ALREADY_INVALID,
  applyClientLogout,
  demoResetImpliesSuccess,
  logoutViaRest,
  scoreApiRoot,
} from './session.js';

test('logout POST uses the current bearer token and /logout', async () => {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, init });
    return { ok: true };
  };
  const result = await logoutViaRest('session-abc', {
    fetchImpl,
    apiRoot: 'http://127.0.0.1:8000/',
  });
  assert.equal(result.revoked, true);
  assert.equal(result.error, null);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'http://127.0.0.1:8000/logout');
  assert.equal(calls[0].init.method, 'POST');
  assert.deepEqual(calls[0].init.headers, { Authorization: 'Bearer session-abc' });
  assert.equal(JSON.stringify(result).includes('session-abc'), false);
});

test('logout success clears stored session locally', () => {
  const storage = new Map([['senitenial_pay_v1_token', 'session-abc']]);
  storage.removeItem = (key) => storage.delete(key);
  const next = applyClientLogout(storage, 'senitenial_pay_v1', { revoked: true, error: null });
  assert.equal(next.sessionToken, '');
  assert.equal(next.lastScore, null);
  assert.equal(next.authError, '');
  assert.equal(next.sessionMayRemain, false);
  assert.equal(storage.has('senitenial_pay_v1_token'), false);
  assert.equal(demoResetImpliesSuccess(next), true);
});

test('invalid session still clears locally and does not claim revocation', async () => {
  const fetchImpl = async () => ({ ok: false, status: 401 });
  const result = await logoutViaRest('session-abc', { fetchImpl, apiRoot: 'http://localhost:8000' });
  assert.equal(result.revoked, false);
  assert.equal(result.error, 'invalid');
  const storage = new Map([['demo_token', 'session-abc']]);
  storage.removeItem = (key) => storage.delete(key);
  const next = applyClientLogout(storage, 'demo', result);
  assert.equal(next.sessionToken, '');
  assert.equal(next.sessionMayRemain, false);
  assert.equal(next.authError, SESSION_ALREADY_INVALID);
  assert.equal(next.authError.includes('session-abc'), false);
  assert.equal(storage.has('demo_token'), false);
  assert.equal(demoResetImpliesSuccess(next), false);
});

test('network failure is unconfirmed and does not keep the token locally', async () => {
  const fetchImpl = async () => {
    throw new Error('offline');
  };
  const result = await logoutViaRest('session-abc', { fetchImpl });
  assert.equal(result.revoked, false);
  assert.equal(result.error, 'network');
  const storage = new Map([['demo_token', 'session-abc']]);
  storage.removeItem = (key) => storage.delete(key);
  const next = applyClientLogout(storage, 'demo', result);
  assert.equal(next.sessionMayRemain, true);
  assert.equal(next.authError, LOCAL_SESSION_UNCONFIRMED);
  assert.equal(demoResetImpliesSuccess(next), false);
  assert.equal(storage.has('demo_token'), false);
});

test('demo reset celebrates only after confirmed revocation', () => {
  assert.equal(demoResetImpliesSuccess({ revoked: true, sessionMayRemain: false }), true);
  assert.equal(demoResetImpliesSuccess({ revoked: false, sessionMayRemain: true }), false);
  assert.equal(demoResetImpliesSuccess({ revoked: false, sessionMayRemain: false }), false);
});

test('missing token skips the request', async () => {
  let called = 0;
  const result = await logoutViaRest('', {
    fetchImpl: async () => {
      called += 1;
      return { ok: true };
    },
  });
  assert.equal(result.revoked, true);
  assert.equal(called, 0);
});

test('score API root defaults without Vite env', () => {
  assert.equal(scoreApiRoot({}), 'http://localhost:8000');
  assert.equal(scoreApiRoot({ VITE_SCORE_API_URL: 'http://127.0.0.1:9' }), 'http://127.0.0.1:9');
});
