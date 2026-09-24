import React, { useState } from 'react';
import {
  QrCode,
  Users,
  Smartphone,
  Building2,
  AtSign,
  ArrowLeftRight,
  Receipt,
  Scale
} from 'lucide-react';
import { useApp } from '../../context/AppContext';

export const QuickActions = () => {
  const {
    setQrModal,
    setActiveTab,
    startPaymentFlow,
    setCheckBalanceModal,
    banks
  } = useApp();

  const [inputModal, setInputModal] = useState({
    isOpen: false,
    type: '', // 'phone', 'upi', 'bank'
    title: ''
  });

  const [inputValue, setInputValue] = useState('');
  const [recipientName, setRecipientName] = useState('');

  const actions = [
    {
      id: 'scan',
      label: 'Scan QR code',
      icon: QrCode,
      color: 'bg-blue-600/20 text-blue-400 border-blue-500/30',
      onClick: () => setQrModal({ isOpen: true, tab: 'scan' })
    },
    {
      id: 'contacts',
      label: 'Pay contacts',
      icon: Users,
      color: 'bg-indigo-600/20 text-indigo-400 border-indigo-500/30',
      onClick: () => {
        // Scroll or focus to People section
        const el = document.getElementById('people-section');
        if (el) el.scrollIntoView({ behavior: 'smooth' });
      }
    },
    {
      id: 'phone',
      label: 'Pay phone number',
      icon: Smartphone,
      color: 'bg-emerald-600/20 text-emerald-400 border-emerald-500/30',
      onClick: () => setInputModal({ isOpen: true, type: 'phone', title: 'Enter Mobile Number' })
    },
    {
      id: 'bank',
      label: 'Bank transfer',
      icon: Building2,
      color: 'bg-sky-600/20 text-sky-400 border-sky-500/30',
      onClick: () => setInputModal({ isOpen: true, type: 'bank', title: 'Bank Account Transfer' })
    },
    {
      id: 'upi',
      label: 'Pay UPI ID',
      icon: AtSign,
      color: 'bg-purple-600/20 text-purple-400 border-purple-500/30',
      onClick: () => setInputModal({ isOpen: true, type: 'upi', title: 'Pay with UPI ID' })
    },
    {
      id: 'self',
      label: 'Self transfer',
      icon: ArrowLeftRight,
      color: 'bg-teal-600/20 text-teal-400 border-teal-500/30',
      onClick: () => {
        startPaymentFlow({
          name: "My HDFC Bank A/C",
          upiId: "aarav.self@hdfcbank",
          avatar: null
        }, '', 'Self Transfer');
      }
    },
    {
      id: 'bills',
      label: 'Pay bills',
      icon: Receipt,
      color: 'bg-amber-600/20 text-amber-400 border-amber-500/30',
      onClick: () => setActiveTab('bills')
    },
    {
      id: 'balance',
      label: 'Check balance',
      icon: Scale,
      color: 'bg-rose-600/20 text-rose-400 border-rose-500/30',
      onClick: () => setCheckBalanceModal({ isOpen: true, bank: banks[0] })
    }
  ];

  const handleCustomSend = (e) => {
    e.preventDefault();
    if (!inputValue) return;

    let payRecipient = {
      name: recipientName || inputValue,
      upiId: inputModal.type === 'upi' ? inputValue : `${inputValue}@senitenial`,
      phone: inputModal.type === 'phone' ? inputValue : ''
    };

    setInputModal({ isOpen: false, type: '', title: '' });
    setInputValue('');
    setRecipientName('');

    startPaymentFlow(payRecipient);
  };

  return (
    <>
      <div className="grid grid-cols-4 gap-y-4 gap-x-2 py-2">
        {actions.map((act) => {
          const Icon = act.icon;
          return (
            <button
              key={act.id}
              onClick={act.onClick}
              className="flex flex-col items-center gap-1.5 p-2 rounded-2xl hover:bg-slate-800/40 transition-all cursor-pointer group"
            >
              <div className={`w-13 h-13 rounded-2xl flex items-center justify-center border shadow-sm group-hover:scale-105 group-hover:shadow-md transition-all ${act.color}`}>
                <Icon className="w-6 h-6 transition-transform group-hover:scale-110" />
              </div>
              <span className="text-[11px] font-medium text-slate-300 text-center leading-tight">
                {act.label}
              </span>
            </button>
          );
        })}
      </div>

      {/* Input modal for custom phone / UPI / bank entry */}
      {inputModal.isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="w-full max-w-sm rounded-3xl bg-slate-900 border border-slate-700/80 p-6 shadow-2xl">
            <h3 className="text-lg font-bold text-white mb-1 font-heading">{inputModal.title}</h3>
            <p className="text-xs text-slate-400 mb-4">Instant zero-fee transfer backed by Sentinel 256-bit encryption.</p>

            <form onSubmit={handleCustomSend} className="space-y-3">
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">
                  Recipient Name (Optional)
                </label>
                <input
                  type="text"
                  placeholder="e.g. Rahul Sharma"
                  value={recipientName}
                  onChange={(e) => setRecipientName(e.target.value)}
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-800 border border-slate-700 text-sm text-white focus:outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">
                  {inputModal.type === 'phone' ? 'Mobile Number' : inputModal.type === 'upi' ? 'UPI ID' : 'Account Number / IFSC'}
                </label>
                <input
                  type={inputModal.type === 'phone' ? 'tel' : 'text'}
                  required
                  placeholder={
                    inputModal.type === 'phone'
                      ? '98765 43210'
                      : inputModal.type === 'upi'
                      ? 'friend@oksbi / name@paytm'
                      : 'Account Number & IFSC'
                  }
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-800 border border-slate-700 text-sm text-white focus:outline-none focus:border-blue-500"
                />
              </div>

              <div className="flex gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setInputModal({ isOpen: false, type: '', title: '' })}
                  className="flex-1 py-2.5 rounded-xl bg-slate-800 text-slate-300 hover:bg-slate-700 font-medium text-xs transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="flex-1 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-medium text-xs shadow-lg shadow-blue-600/30 transition-all cursor-pointer"
                >
                  Proceed
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
};
