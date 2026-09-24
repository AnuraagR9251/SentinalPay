import React from 'react';
import { Check, ShieldCheck, Gift, Share2, Receipt, ArrowRight } from 'lucide-react';
import { useApp } from '../../context/AppContext';

export const PaymentSuccessModal = () => {
  const {
    paymentSuccessModal,
    setPaymentSuccessModal,
    setScratchCardModal,
    setReceiptModal,
    user
  } = useApp();

  const { isOpen, transaction, scratchReward } = paymentSuccessModal;

  if (!isOpen || !transaction) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fade-in">
      <div className="w-full max-w-sm rounded-[36px] bg-slate-900 border border-slate-700/80 p-6 text-center shadow-2xl relative overflow-hidden">
        {/* Glow backdrop */}
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-48 h-48 bg-emerald-500/20 rounded-full blur-3xl pointer-events-none" />

        {/* Animated Green Checkmark */}
        <div className="relative my-4 inline-flex items-center justify-center">
          <div className="w-20 h-20 rounded-full bg-emerald-500/20 border-2 border-emerald-400/40 flex items-center justify-center animate-pulse">
            <div className="w-14 h-14 rounded-full bg-emerald-500 flex items-center justify-center text-white shadow-lg shadow-emerald-500/50">
              <Check className="w-8 h-8 stroke-[3]" />
            </div>
          </div>
        </div>

        {/* Success Title & Amount */}
        <div className="space-y-1 mb-6">
          <span className="text-xs uppercase tracking-wider font-bold text-emerald-400">
            Payment Successful
          </span>
          <h2 className="text-3xl font-black text-white font-heading">
            {user.currency}{transaction.amount.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
          </h2>
          <p className="text-sm text-slate-300 font-medium">
            Paid to <span className="text-white font-semibold">{transaction.title}</span>
          </p>
          <p className="text-xs text-slate-400">{transaction.timestamp}</p>
        </div>

        {/* Transaction Details Pill */}
        <div className="p-3.5 rounded-2xl bg-slate-950/60 border border-slate-800 text-left text-xs space-y-2 mb-4">
          <div className="flex justify-between items-center text-slate-400">
            <span>Payment Method</span>
            <span className="text-slate-200 font-medium">{transaction.method}</span>
          </div>
          <div className="flex justify-between items-center text-slate-400">
            <span>UPI Ref / UTR</span>
            <span className="text-slate-200 font-mono text-[11px]">{transaction.utr}</span>
          </div>
          {transaction.note && (
            <div className="flex justify-between items-center text-slate-400">
              <span>Note</span>
              <span className="text-slate-200">{transaction.note}</span>
            </div>
          )}
        </div>

        {/* Scratch Card Unlock Banner (If Won) */}
        {scratchReward && (
          <div
            onClick={() => {
              setPaymentSuccessModal(prev => ({ ...prev, isOpen: false }));
              setScratchCardModal({ isOpen: true, reward: scratchReward });
            }}
            className="p-3.5 rounded-2xl bg-gradient-to-r from-amber-600/30 to-purple-600/30 border border-amber-500/40 text-left mb-4 flex items-center justify-between cursor-pointer group hover:scale-[1.02] transition-all"
          >
            <div className="flex items-center gap-2.5">
              <div className="p-2 rounded-xl bg-amber-500/20 text-amber-300">
                <Gift className="w-5 h-5 animate-bounce" />
              </div>
              <div>
                <p className="text-xs font-bold text-white">You won a Scratch Card!</p>
                <p className="text-[10px] text-amber-300">Tap to scratch & reveal cashback</p>
              </div>
            </div>
            <ArrowRight className="w-4 h-4 text-amber-300 group-hover:translate-x-1 transition-transform" />
          </div>
        )}

        {/* Action Buttons */}
        <div className="space-y-2">
          <button
            onClick={() => {
              setPaymentSuccessModal(prev => ({ ...prev, isOpen: false }));
              setReceiptModal({ isOpen: true, transaction });
            }}
            className="w-full py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
          >
            <Receipt className="w-3.5 h-3.5 text-blue-400" />
            <span>View Receipt & Details</span>
          </button>

          <button
            onClick={() => setPaymentSuccessModal({ isOpen: false, transaction: null, scratchReward: null })}
            className="w-full py-3 rounded-2xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold shadow-lg shadow-blue-600/30 transition-all cursor-pointer"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
};
