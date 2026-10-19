export function retryDelayMs(retryAfter, fallbackMs = 8000) {
  const raw = retryAfter == null ? '' : String(retryAfter).trim();
  if (/^\d+$/.test(raw)) {
    return Math.max(1000, Number(raw) * 1000);
  }
  return fallbackMs;
}

export function graphqlFailure(body) {
  const first = (body && body.errors && body.errors[0]) || {};
  const extensions = first.extensions || {};
  const status = Number(extensions.httpStatus || extensions.code || 0);
  const message = String(first.message || 'request failed');
  const err = new Error(message);
  err.graphql = true;
  err.httpStatus = status || undefined;
  err.rateLimited = status === 429 || message.toLowerCase() === 'too many requests';
  return err;
}
