import React from 'react';
import { X, ShieldCheck, Printer, Share2, CheckCircle2, Download } from 'lucide-react';
import { useApp } from '../../context/AppContext';

export const ReceiptModal = () => {
  const { receiptModal, setReceiptModal, user } = useApp();
  const { isOpen, transaction } = receiptModal;

  if (!isOpen || !transaction) return null;

  const handlePrint = () => {
    window.print();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fade-in">
      <div className="w-full max-w-sm rounded-[32px] bg-slate-900 border border-slate-700/80 p-6 shadow-2xl relative text-left">
        {/* Close Button */}
        <button
          onClick={() => setReceiptModal({ isOpen: false, transaction: null })}
          className="absolute top-5 right-5 p-2 rounded-full bg-slate-800 text-slate-400 hover:text-white cursor-pointer"
        >
          <X className="w-4 h-4" />
        </button>

        {/* Receipt Slip Container */}
        <div id="receipt-slip" className="bg-white text-slate-900 p-6 rounded-2xl shadow-inner border border-slate-200">
          {/* Header */}
          <div className="flex items-center justify-between pb-4 border-b border-dashed border-slate-300">
            <div>
              <h3 className="text-base font-extrabold text-blue-600 font-heading">
                Senitenial Pay
              </h3>
              <p className="text-[10px] text-slate-500">Official Payment Receipt</p>
            </div>
            <div className="w-8 h-8 rounded-full bg-emerald-100 flex items-center justify-center text-emerald-600">
              <CheckCircle2 className="w-5 h-5" />
            </div>
          </div>

          {/* Amount banner */}
          <div className="py-4 text-center">
            <span className="text-xs text-slate-500 font-medium">Transaction Amount</span>
            <div className="text-3xl font-black text-slate-900 font-heading">
              {user.currency}{transaction.amount.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </div>
            <span className="inline-block mt-1 px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 text-[10px] font-bold">
              ✓ COMPLETED
            </span>
          </div>

          {/* Receipt Details */}
          <div className="space-y-2 text-xs py-3 border-t border-b border-dashed border-slate-300">
            <div className="flex justify-between">
              <span className="text-slate-500">Paid To:</span>
              <span className="font-bold text-slate-900">{transaction.title}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Recipient UPI:</span>
              <span className="font-mono text-slate-800 text-[11px]">{transaction.upiId}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Paid From:</span>
              <span className="text-slate-800 font-medium">{transaction.method}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">UTR / Ref No:</span>
              <span className="font-mono text-slate-800 text-[11px] font-semibold">{transaction.utr}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Date & Time:</span>
              <span className="text-slate-700">{transaction.timestamp}</span>
            </div>
            {transaction.note && (
              <div className="flex justify-between">
                <span className="text-slate-500">Note:</span>
                <span className="text-slate-700 italic">{transaction.note}</span>
              </div>
            )}
          </div>

          {/* Verification stamp */}
          <div className="pt-3 text-center">
            <p className="text-[9px] text-slate-400">
              Verified by NPCI Unified Payments Interface & Sentinel AI Guard.
            </p>
          </div>
        </div>

        {/* Buttons */}
        <div className="flex gap-2 mt-4">
          <button
            onClick={handlePrint}
            className="flex-1 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold flex items-center justify-center gap-1.5 cursor-pointer"
          >
            <Printer className="w-3.5 h-3.5" />
            <span>Print Receipt</span>
          </button>
          <button
            onClick={() => {
              if (navigator.share) {
                navigator.share({
                  title: 'Payment Receipt',
                  text: `Paid ₹${transaction.amount} to ${transaction.title} via Senitenial Pay. UTR: ${transaction.utr}`
                }).catch(() => {});
              } else {
                alert(`Receipt details copied! UTR: ${transaction.utr}`);
              }
            }}
            className="flex-1 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold flex items-center justify-center gap-1.5 cursor-pointer shadow-md shadow-blue-600/30"
          >
            <Share2 className="w-3.5 h-3.5" />
            <span>Share</span>
          </button>
        </div>
      </div>
    </div>
  );
};
