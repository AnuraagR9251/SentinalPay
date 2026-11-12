// Wallet payments use tx- ids. Lab and isolated scenarios use their own ids and do not call this.

export const UPI_MAX_RUPEES = 100000;

export function withinUpiLimit(amount) {
  const rupees = Number(amount);
  return Number.isFinite(rupees) && rupees > 0 && rupees <= UPI_MAX_RUPEES;
}

export function attemptKey({ userId, amount, merchantId, deviceId, latitude, longitude }) {
  const lat = latitude == null || latitude === '' || Number.isNaN(Number(latitude)) ? '' : Number(latitude).toFixed(5);
  const lon = longitude == null || longitude === '' || Number.isNaN(Number(longitude)) ? '' : Number(longitude).toFixed(5);
  const rupees = Number(amount);
  return [
    String(userId || ''),
    Number.isFinite(rupees) ? rupees.toFixed(2) : '',
    'INR',
    String(merchantId || ''),
    String(deviceId || ''),
    lat,
    lon,
  ].join('|');
}

export function claimAttempt(cache, key, nowMs) {
  const hit = cache[key];
  if (hit) return hit;
  const created = {
    transactionId: `tx-${nowMs}`,
    timestamp: new Date(nowMs).toISOString(),
  };
  cache[key] = created;
  return created;
}

export function releaseAttempt(cache, key) {
  delete cache[key];
}
