import React, { useState } from 'react';
import { Eye, EyeOff, ShieldCheck, ArrowUpRight, Plus, RefreshCw, QrCode } from 'lucide-react';
import { useApp } from '../../context/AppContext';

export const BalanceCard = () => {
  const { user, banks, setQrModal, setCheckBalanceModal, startPaymentFlow } = useApp();
  const [showBalance, setShowBalance] = useState(true);

  const primaryBank = banks.find(b => b.isPrimary) || banks[0];

  return (
    <div className="relative overflow-hidden rounded-3xl p-6 bg-gradient-to-br from-blue-900/60 via-slate-900 to-indigo-950/80 border border-blue-500/20 shadow-xl shadow-blue-950/40">
      {/* Decorative ambient lights */}
      <div className="absolute top-0 right-0 -mr-12 -mt-12 w-48 h-48 rounded-full bg-blue-500/10 blur-3xl pointer-events-none" />
      <div className="absolute bottom-0 left-0 -ml-12 -mb-12 w-48 h-48 rounded-full bg-emerald-500/10 blur-3xl pointer-events-none" />

      {/* Top row: Security status & QR button */}
      <div className="flex items-center justify-between mb-4">
        <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-medium">
          <ShieldCheck className="w-3.5 h-3.5" />
          <span>Sentinel Guard: {user.securityScore}</span>
        </div>

        <button
          onClick={() => setQrModal({ isOpen: true, tab: 'myqr' })}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-xl bg-slate-800/80 hover:bg-slate-800 border border-slate-700/60 text-xs text-slate-300 hover:text-white transition-all cursor-pointer"
        >
          <QrCode className="w-3.5 h-3.5 text-blue-400" />
          <span>My QR</span>
        </button>
      </div>

      {/* Balance display */}
      <div className="mb-4">
        <div className="flex items-center gap-2 text-slate-400 text-xs font-medium mb-1">
          <span>Senitenial Reserve Balance</span>
          <button
            onClick={() => setShowBalance(!showBalance)}
            className="hover:text-slate-200 transition-colors cursor-pointer"
          >
            {showBalance ? <Eye className="w-3.5 h-3.5" /> : <EyeOff className="w-3.5 h-3.5" />}
          </button>
        </div>

        <div className="flex items-baseline gap-2">
          <span className="text-3xl sm:text-4xl font-extrabold tracking-tight text-white font-heading">
            {showBalance ? `${user.currency} ${user.walletBalance.toLocaleString('en-IN', { minimumFractionDigits: 2 })}` : '••••••••'}
          </span>
          <span className="text-xs px-2 py-0.5 rounded-md bg-blue-500/20 text-blue-300 font-semibold">
            Instant UPI
          </span>
        </div>
      </div>

      {/* Linked bank glance & check balance button */}
      <div className="pt-3 border-t border-slate-800/80 flex items-center justify-between text-xs">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-blue-600/30 text-blue-400 font-bold flex items-center justify-center text-[10px]">
            {primaryBank?.logoText || "SBI"}
          </div>
          <div>
            <p className="font-semibold text-slate-200">{primaryBank?.bankName}</p>
            <p className="text-slate-400 text-[10px]">{primaryBank?.accountNumber}</p>
          </div>
        </div>

        <button
          onClick={() => setCheckBalanceModal({ isOpen: true, bank: primaryBank })}
          className="inline-flex items-center gap-1 text-blue-400 hover:text-blue-300 font-medium py-1 px-2.5 rounded-lg bg-blue-500/10 hover:bg-blue-500/20 border border-blue-500/20 transition-all cursor-pointer"
        >
          <RefreshCw className="w-3 h-3" />
          <span>Check Balance</span>
        </button>
      </div>
    </div>
  );
};
