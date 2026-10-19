const DEFAULT_API = 'http://localhost:8000';

export const LOCAL_SESSION_UNCONFIRMED =
  'Signed out on this device. The server could not confirm session revocation.';

export const SESSION_ALREADY_INVALID =
  'This sandbox session was already invalid. Signed out on this device.';

export function scoreApiRoot(env) {
  const source = env || (typeof import.meta !== 'undefined' ? import.meta.env : undefined);
  return (source && source.VITE_SCORE_API_URL) || DEFAULT_API;
}

export async function logoutViaRest(token, options = {}) {
  if (!token) {
    return { revoked: true, error: null };
  }
  const fetchImpl = options.fetchImpl || globalThis.fetch;
  const apiRoot = String(options.apiRoot || scoreApiRoot()).replace(/\/$/, '');
  let response;
  try {
    response = await fetchImpl(`${apiRoot}/logout`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    return { revoked: false, error: 'network' };
  }
  if (!response) {
    return { revoked: false, error: 'http' };
  }
  if (response.status === 401) {
    return { revoked: false, error: 'invalid' };
  }
  if (!response.ok) {
    return { revoked: false, error: 'http' };
  }
  return { revoked: true, error: null };
}

export function applyClientLogout(storage, keyPrefix, { revoked, error } = {}) {
  storage.removeItem(`${keyPrefix}_token`);
  const sessionMayRemain = Boolean(!revoked && error && error !== 'invalid');
  let authError = '';
  if (!revoked) {
    authError = error === 'invalid' ? SESSION_ALREADY_INVALID : LOCAL_SESSION_UNCONFIRMED;
  }
  return {
    sessionToken: '',
    lastScore: null,
    authError,
    revoked: Boolean(revoked),
    sessionMayRemain,
  };
}

export function demoResetImpliesSuccess({ revoked }) {
  return Boolean(revoked);
}
