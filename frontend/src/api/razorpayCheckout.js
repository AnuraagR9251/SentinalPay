export function rupeesToPaise(rupees) {
  const value = Number(rupees);
  if (!Number.isFinite(value) || value <= 0) return null;
  const paise = Math.round(value * 100);
  return paise >= 100 ? paise : null;
}

export const SANDBOX_PREFILL = {
  name: 'Aarav Sharma',
  email: 'aarav.sharma@example.com',
  contact: '9000090000',
};

export function checkoutOptions({ key, order, onSuccess, onDismiss }) {
  return {
    key,
    amount: order.amount,
    currency: order.currency || 'INR',
    order_id: order.order_id,
    name: 'SentinalPay',
    description: 'Domestic test card 4100280000001007',
    prefill: SANDBOX_PREFILL,
    readonly: { name: true, email: true, contact: true },
    hidden: { email: true, contact: true },
    remember_customer: false,
    method: { card: true, upi: false, netbanking: false, wallet: false, emi: false, paylater: false },
    handler: onSuccess,
    modal: { ondismiss: onDismiss, confirm_close: false },
  };
}

export function openRazorpayCheckout({ key, order, onSuccess, onDismiss, onFailed }) {
  const Razorpay = typeof window !== 'undefined' ? window.Razorpay : undefined;
  if (!key || !Razorpay || !order || !order.order_id) {
    throw new Error('Razorpay checkout is not available');
  }
  const checkout = new Razorpay(checkoutOptions({ key, order, onSuccess, onDismiss }));
  checkout.on('payment.failed', (response) => {
    const description = response && response.error && response.error.description;
    onFailed(description || 'Payment failed');
  });
  checkout.open();
  return checkout;
}
