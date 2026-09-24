import React, { useState, useEffect } from 'react';
import { X, ShieldCheck, ChevronDown, Check, ArrowRight } from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { sound } from '../../utils/audio';

export const PaymentModal = () => {
  const {
    paymentModal,
    setPaymentModal,
    setUpiPinModal,
    scoreAndExecutePayment,
    banks,
    user
  } = useApp();

  const { isOpen, recipient, prefillAmount, prefillCategory, defaultMethod } = paymentModal;

  const [amount, setAmount] = useState('');
  const [note, setNote] = useState('');
  const [selectedMethod, setSelectedMethod] = useState('');
  const [category, setCategory] = useState('Payment');
  const [showMethodDropdown, setShowMethodDropdown] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setAmount(prefillAmount || '');
      setCategory(prefillCategory || 'Payment');
      setNote('');
      setSelectedMethod(defaultMethod || `${banks[0]?.bankName} (${banks[0]?.accountNumber})`);
    }
  }, [isOpen, prefillAmount, prefillCategory, defaultMethod, banks]);

  if (!isOpen || !recipient) return null;

  const categories = ['Dining', 'Shopping', 'Bills', 'Groceries', 'Rent', 'Travel', 'General'];

  const quickAmounts = [100, 200, 500, 1000, 2000];

  const handleProceedToPin = (e) => {
    e.preventDefault();
    const num = parseFloat(amount);
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
                value={amount}
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
            type="submit"
            disabled={!amount || parseFloat(amount) <= 0}
            className="w-full py-3.5 rounded-2xl bg-gradient-to-r from-blue-600 via-indigo-600 to-emerald-600 hover:from-blue-500 hover:to-emerald-500 disabled:opacity-50 text-white font-bold text-sm shadow-xl shadow-blue-600/30 transition-all flex items-center justify-center gap-2 cursor-pointer"
          >
            <span>Proceed to Pay {user.currency}{amount || '0'}</span>
            <ArrowRight className="w-4 h-4" />
          </button>
        </form>
      </div>
    </div>
  );
};
