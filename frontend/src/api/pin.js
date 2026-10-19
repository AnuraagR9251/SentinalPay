export function pinFeedback(result) {
  const payload = result && typeof result === 'object' ? result : { ok: Boolean(result), error: '' };
  if (payload.ok) return { ok: true, message: '', failPayment: false };
  const code = String(payload.error || '').toLowerCase().replace(/\s+/g, '_');
  if (code === 'locked' || code.includes('too_many')) {
    return {
      ok: false,
      message: 'Payment failed after 3 incorrect OTP attempts.',
      failPayment: true,
    };
  }
  return { ok: false, message: 'Incorrect OTP', failPayment: false };
}
