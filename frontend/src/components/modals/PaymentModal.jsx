import React, { useState, useEffect } from 'react';
import { X, ShieldCheck, ChevronDown, Check, ArrowRight } from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { scoreApiRoot } from '../../api/session';
import { openRazorpayCheckout, rupeesToPaise } from '../../api/razorpayCheckout';
import { holdView, mayMutateBalance } from '../../api/holdAssessment';
import { SECONDARY_COPY } from '../../api/scoreDisplay';
import { sound } from '../../utils/audio';

export const PaymentModal = () => {
  const {
    paymentModal,
    setPaymentModal,
    setUpiPinModal,
    scoreAndExecutePayment,
    banks,
    user,
    sessionToken,
    executePayment,
    setRiskGateModal,
    setLastScore
  } = useApp();

  const { isOpen, recipient, prefillAmount, prefillCategory, defaultMethod } = paymentModal;

  const [amount, setAmount] = useState('');
  const [note, setNote] = useState('');
  const [selectedMethod, setSelectedMethod] = useState('');
  const [category, setCategory] = useState('Payment');
  const [showMethodDropdown, setShowMethodDropdown] = useState(false);
  const [razorpayError, setRazorpayError] = useState('');

  useEffect(() => {
    if (isOpen) {
      setAmount(prefillAmount || '');
      setCategory(prefillCategory || 'Payment');
      setNote('');
      setRazorpayError('');
      setSelectedMethod(defaultMethod || `${banks[0]?.bankName} (${banks[0]?.accountNumber})`);
    }
  }, [isOpen, prefillAmount, prefillCategory, defaultMethod, banks]);

  if (!isOpen || !recipient) return null;

  const categories = ['Dining', 'Shopping', 'Bills', 'Groceries', 'Rent', 'Travel', 'General'];

  const payAmount = amount !== '' ? amount : (prefillAmount || '');
  const quickAmounts = [100, 200, 500, 1000, 2000];

  const payWithRazorpay = async () => {
    setRazorpayError('');
    const paise = rupeesToPaise(payAmount);
    if (!paise) {
      setRazorpayError('Minimum amount is ₹1');
      return;
    }
    const key = import.meta.env.VITE_RAZORPAY_KEY_ID;
    if (!key) {
      setRazorpayError('Razorpay key is not configured');
      return;
    }
    const num = parseFloat(payAmount);
    const transactionId = `tx-${Date.now()}`;
    setPaymentModal((prev) => ({ ...prev, isOpen: false }));
    setRiskGateModal({
      isOpen: true,
      phase: 'scanning',
      payeeName: recipient.name,
      amount: num
    });
    await placeCheckout({ key, paise, num, transactionId });
  };

  const placeCheckout = async ({ key, paise, num, transactionId }) => {
    const showGate = (phase, extra = {}) => setRiskGateModal({
      isOpen: true,
      phase,
      payeeName: recipient.name,
      amount: num,
      ...extra
    });
    try {
      const headers = { 'Content-Type': 'application/json' };
      if (sessionToken) headers.Authorization = `Bearer ${sessionToken}`;
      const loc = user.location || {};
      const created = await fetch(`${scoreApiRoot().replace(/\/$/, '')}/api/create-order`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          amount: paise,
          currency: 'INR',
          transaction_id: transactionId,
          user_id: user.upiId,
          merchant_id: recipient.upiId || 'upi@senitenial',
          merchant_category: category || 'p2p',
          device_id: user.deviceId || null,
          timestamp: new Date().toISOString(),
          latitude: loc.lat,
          longitude: loc.lon,
          receipt: transactionId.slice(0, 40),
        }),
      });
      const body = await created.json().catch(() => ({}));
      const detail = body.detail;
      const action = detail && typeof detail === 'object' ? detail.action : null;
      if (created.status === 403 && action === 'STEP_UP') {
        setRiskGateModal({ isOpen: false, phase: 'idle', payeeName: '', amount: 0 });
        setLastScore({
          challenge_id: detail.challenge_id,
          action: 'STEP_UP',
          canonical_decision: detail.decision,
          canonical_risk_score: detail.risk_score,
          risk_tier: 'STEP_UP'
        });
        setUpiPinModal({
          isOpen: true,
          stepUp: true,
          review: false,
          amount: num,
          recipientName: recipient.name || 'Merchant',
          purpose: 'Step-up check',
          onComplete: () => placeCheckout({ key, paise, num, transactionId })
        });
        return;
      }
      if (created.status === 403 && action === 'HOLD') {
        const view = holdView({
          outcome: detail.secondary_outcome,
          reasons: detail.reasons,
          deadline: detail.deadline,
          created_at: detail.created_at,
          decision: detail.decision || 'REVIEW',
          risk_score: detail.risk_score,
        });
        showGate(view.phase === 'hold' ? 'hold' : view.phase, {
          ...view,
          transactionId,
          onContinue: () => placeCheckout({ key, paise, num, transactionId }),
        });
        return;
      }
      if (created.status === 403) {
        showGate('block', {
          canonicalDecision: (detail && detail.decision) || 'BLOCK',
          canonicalRiskScore: detail && detail.risk_score,
          riskTier: 'BLOCK',
          message: 'Sentinel blocked this payment. Razorpay was not opened.'
        });
        return;
      }
      if (!created.ok) {
        const message = typeof detail === 'string' ? detail : 'Could not start payment';
        showGate('error', { message });
        return;
      }
      const startRazorpay = () => {
        setRiskGateModal({ isOpen: false, phase: 'idle', payeeName: '', amount: 0 });
        openRazorpayCheckout({
        key,
        order: body,
        onSuccess: async (response) => {
          const verified = await fetch(`${scoreApiRoot().replace(/\/$/, '')}/api/verify-payment`, {
            method: 'POST',
            headers,
            body: JSON.stringify({
              razorpay_order_id: response.razorpay_order_id,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_signature: response.razorpay_signature,
              transaction_id: transactionId,
            }),
          });
          const verdict = await verified.json().catch(() => ({}));
          if (!verified.ok) {
            showGate('error', { message: verdict.detail || 'Payment was not verified' });
            return;
          }
          if (mayMutateBalance(verdict.settled)) {
            executePayment({
              recipient,
              amount: num,
              category,
              method: 'Razorpay',
              note: 'Sandbox ledger — not a bank settlement',
              transactionId,
              score: {
                canonical_decision: body.decision,
                canonical_risk_score: body.risk_score
              },
              razorpay: true
            });
            return;
          }
          showGate(verdict.payment_status === 'failed' ? 'block' : 'error', {
            message: verdict.payment_status === 'failed'
              ? 'Payment failed. Sandbox balance was not changed.'
              : 'Payment is not settled. Sandbox balance was not changed.',
            canonicalDecision: body.decision,
            canonicalRiskScore: body.risk_score
          });
        },
        onDismiss: () => showGate('error', { message: 'Payment cancelled. Sandbox balance was not changed.' }),
        onFailed: (message) => showGate('block', {
          message: message || 'Payment failed. Sandbox balance was not changed.',
          canonicalDecision: body.decision,
          canonicalRiskScore: body.risk_score
        }),
      });
      };
      if (body.secondary_outcome === 'ALLOW') {
        showGate('hold', {
          canonicalDecision: body.decision,
          canonicalRiskScore: body.risk_score,
          riskTier: 'HOLD',
          secondaryOutcome: 'ALLOW',
          deadline: new Date(Date.now() + 15000).toISOString(),
          message: SECONDARY_COPY.PENDING,
          onContinue: startRazorpay
        });
        return;
      }
      startRazorpay();
    } catch (err) {
      showGate('error', { message: err && err.message ? err.message : 'Could not start payment' });
    }
  };

  const handleProceedToPin = (e) => {
    e.preventDefault();
    const num = parseFloat(payAmount);
    if (isNaN(num) || num <= 0) return;

    sound.playTap();

    // Close payment input modal and open secure UPI PIN modal
    setPaymentModal(prev => ({ ...prev, isOpen: false }));

    setUpiPinModal({
      isOpen: true,
      amount: num,
      recipientName: recipient.name || 'Merchant',
      purpose: note || category,
      onComplete: () => {
        scoreAndExecutePayment({
          recipient,
          amount: num,
          category,
          method: selectedMethod,
          note
        });
      }
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/70 backdrop-blur-md animate-fade-in p-0 sm:p-4">
      <div className="w-full max-w-md bg-slate-900 border border-slate-700/80 rounded-t-[32px] sm:rounded-3xl p-6 shadow-2xl relative">
        {/* Close Button */}
        <button
          onClick={() => setPaymentModal({ isOpen: false, recipient: null })}
          className="absolute top-5 right-5 p-2 rounded-full bg-slate-800 text-slate-400 hover:text-white cursor-pointer"
        >
          <X className="w-4 h-4" />
        </button>

        {/* Recipient Header */}
        <div className="flex items-center gap-3 mb-6 pr-8">
          {recipient.avatar ? (
            <img
              src={recipient.avatar}
              alt={recipient.name}
              className="w-13 h-13 rounded-2xl object-cover ring-2 ring-blue-500/40"
            />
          ) : (
            <div className="w-13 h-13 rounded-2xl bg-gradient-to-tr from-blue-600 to-indigo-600 flex items-center justify-center text-white font-bold text-lg font-heading shadow-md">
              {recipient.name?.substring(0, 2).toUpperCase() || 'SP'}
            </div>
          )}

          <div>
            <div className="flex items-center gap-1.5">
              <h3 className="text-base font-bold text-white font-heading">{recipient.name}</h3>
              <ShieldCheck className="w-4 h-4 text-emerald-400" />
            </div>
            <p className="text-xs text-slate-400">{recipient.upiId}</p>
            {recipient.phone && <p className="text-[11px] text-slate-500">{recipient.phone}</p>}
          </div>
        </div>

        <form onSubmit={handleProceedToPin} className="space-y-4">
          {/* Amount Input */}
          <div className="text-center py-2 bg-slate-950/60 rounded-2xl border border-slate-800 p-4">
            <span className="text-xs text-slate-400 font-medium">Enter Amount</span>
            <div className="flex items-center justify-center gap-2 mt-1">
              <span className="text-3xl font-bold text-slate-300 font-heading">
                {user.currency}
              </span>
              <input
                type="number"
                step="any"
                required
                autoFocus
                placeholder="0"
                value={payAmount}
                onChange={(e) => setAmount(e.target.value)}
                className="w-44 text-3xl sm:text-4xl font-extrabold text-white bg-transparent text-center focus:outline-none placeholder-slate-600 font-heading"
              />
            </div>

            {/* Quick Amount Chips */}
            <div className="flex justify-center gap-1.5 mt-3 flex-wrap">
              {quickAmounts.map(val => (
                <button
                  type="button"
                  key={val}
                  onClick={() => setAmount(String(val))}
                  className="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-300 font-medium transition-colors cursor-pointer"
                >
                  +{user.currency}{val}
                </button>
              ))}
            </div>
          </div>

          {/* Note & Category */}
          <div className="grid grid-cols-1 gap-2">
            <div>
              <input
                type="text"
                placeholder="What is this for? (e.g., Dinner, Rent)"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                className="w-full px-3.5 py-2.5 rounded-xl bg-slate-800/80 border border-slate-700 text-xs text-white placeholder-slate-400 focus:outline-none focus:border-blue-500"
              />
            </div>

            {/* Category Pills */}
            <div className="flex gap-1.5 overflow-x-auto no-scrollbar py-1">
              {categories.map((cat) => (
                <button
                  type="button"
                  key={cat}
                  onClick={() => setCategory(cat)}
                  className={`px-3 py-1 rounded-full text-[11px] font-medium whitespace-nowrap transition-all cursor-pointer ${
                    category === cat
                      ? 'bg-blue-600 text-white shadow-sm'
                      : 'bg-slate-800 text-slate-400 hover:text-white'
                  }`}
                >
                  {cat}
                </button>
              ))}
            </div>
          </div>

          {/* Payment Method / Bank Selector */}
          <div className="relative">
            <label className="block text-[11px] font-semibold text-slate-400 mb-1">
              Paying from
            </label>
            <button
              type="button"
              onClick={() => setShowMethodDropdown(!showMethodDropdown)}
              className="w-full px-3.5 py-2.5 rounded-xl bg-slate-800 border border-slate-700 text-xs text-white flex items-center justify-between cursor-pointer hover:border-slate-600"
            >
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-emerald-400" />
                <span className="font-medium truncate">{selectedMethod}</span>
              </div>
              <ChevronDown className="w-4 h-4 text-slate-400" />
            </button>

            {/* Dropdown Options */}
            {showMethodDropdown && (
              <div className="absolute bottom-full mb-1 left-0 right-0 bg-slate-800 border border-slate-700 rounded-xl shadow-2xl p-1 z-30 space-y-1">
                {banks.map(bank => (
                  <button
                    type="button"
                    key={bank.id}
                    onClick={() => {
                      setSelectedMethod(`${bank.bankName} (${bank.accountNumber})`);
                      setShowMethodDropdown(false);
                    }}
                    className="w-full px-3 py-2 text-left text-xs rounded-lg hover:bg-slate-700 flex items-center justify-between text-white cursor-pointer"
                  >
                    <span>{bank.bankName} ({bank.accountNumber})</span>
                    <span className="text-[10px] text-slate-400">₹{bank.balance.toLocaleString()}</span>
                  </button>
                ))}
                <button
                  type="button"
                  onClick={() => {
                    setSelectedMethod("Senitenial Reserve Wallet");
                    setShowMethodDropdown(false);
                  }}
                  className="w-full px-3 py-2 text-left text-xs rounded-lg hover:bg-slate-700 flex items-center justify-between text-white cursor-pointer"
                >
                  <span>Senitenial Reserve Wallet</span>
                  <span className="text-[10px] text-emerald-400">₹{user.walletBalance.toLocaleString()}</span>
                </button>
              </div>
            )}
          </div>

          {/* Submit Button */}
          <button
            type="button"
            disabled={!payAmount || parseFloat(payAmount) <= 0}
            onClick={payWithRazorpay}
            className="w-full py-3 rounded-2xl bg-slate-800 border border-slate-600 text-white font-bold text-sm cursor-pointer disabled:opacity-50"
          >
            Pay with Razorpay
          </button>
          <p className="text-[10px] text-center text-slate-500">
            Domestic test card 4100 2800 0000 1007, any future expiry, any CVV.
          </p>
          {razorpayError && <p className="text-xs text-center text-rose-400">{razorpayError}</p>}
          <button
            type="submit"
            disabled={!payAmount || parseFloat(payAmount) <= 0}
            className="w-full py-3.5 rounded-2xl bg-gradient-to-r from-blue-600 via-indigo-600 to-emerald-600 hover:from-blue-500 hover:to-emerald-500 disabled:opacity-50 text-white font-bold text-sm shadow-xl shadow-blue-600/30 transition-all flex items-center justify-center gap-2 cursor-pointer"
          >
            <span>Proceed to Pay {user.currency}{payAmount || '0'}</span>
            <ArrowRight className="w-4 h-4" />
          </button>
          <p className="text-[10px] text-center text-slate-500 mt-2">
            Sandbox debit only — not NPCI or bank settlement.
          </p>
        </form>
      </div>
    </div>
  );
};
