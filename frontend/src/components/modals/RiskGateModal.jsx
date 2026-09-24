import React from 'react';
import { ShieldAlert, ShieldX, LoaderCircle, Clock3 } from 'lucide-react';
import { useApp } from '../../context/AppContext';

export const RiskGateModal = () => {
  const { riskGateModal, setRiskGateModal, user } = useApp();
  const { isOpen, phase, riskTier, riskScore, payeeName, amount } = riskGateModal;

  if (!isOpen) return null;

  const close = () => setRiskGateModal({
    isOpen: false,
    phase: 'idle',
    riskTier: null,
    riskScore: null,
    payeeName: '',
    amount: 0
  });

  if (phase === 'scanning') {
    return (
      <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fade-in">
        <div className="w-full max-w-sm rounded-[36px] bg-slate-900 border border-blue-500/30 p-6 text-center shadow-2xl relative overflow-hidden">
          <div className="absolute top-0 left-1/2 -translate-x-1/2 w-48 h-48 bg-blue-500/20 rounded-full blur-3xl pointer-events-none" />
          <div className="relative my-6 inline-flex items-center justify-center">
            <LoaderCircle className="w-16 h-16 text-blue-400 animate-spin" />
          </div>
          <p className="text-xs uppercase tracking-wider font-bold text-blue-400">Sentinel scan</p>
          <h2 className="text-xl font-black text-white font-heading mt-1">Checking this payment</h2>
          <p className="text-sm text-slate-400 mt-2">
            Scoring {user.currency}{Number(amount || 0).toLocaleString('en-IN')} to {payeeName || 'payee'}
          </p>
          <p className="text-[11px] text-slate-500 mt-4">Live risk model — this is not instant on purpose.</p>
        </div>
      </div>
    );
  }

  if (phase === 'hold') {
    return (
      <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fade-in">
        <div className="w-full max-w-sm rounded-[36px] bg-slate-900 border border-amber-500/40 p-6 text-center shadow-2xl relative overflow-hidden">
          <div className="absolute top-0 left-1/2 -translate-x-1/2 w-48 h-48 bg-amber-500/15 rounded-full blur-3xl pointer-events-none" />
          <div className="relative my-4 inline-flex items-center justify-center">
            <div className="w-16 h-16 rounded-full bg-amber-500/20 border-2 border-amber-400/40 flex items-center justify-center">
              <Clock3 className="w-8 h-8 text-amber-300" />
            </div>
          </div>
          <p className="text-xs uppercase tracking-wider font-bold text-amber-400">Payment under review</p>
          <h2 className="text-2xl font-black text-white font-heading mt-1">
            {user.currency}{Number(amount || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
          </h2>
          <p className="text-sm text-slate-300 mt-2">
            Held before settlement to {payeeName || 'payee'}. No money has left your account.
          </p>
          <p className="text-[11px] text-slate-500 mt-3 font-mono">
            {riskTier} · score {riskScore != null ? Number(riskScore).toFixed(3) : '—'}
          </p>
          <button
            onClick={close}
            className="w-full mt-6 py-3 rounded-2xl bg-amber-600 hover:bg-amber-500 text-white text-xs font-bold cursor-pointer"
          >
            OK
          </button>
        </div>
      </div>
    );
  }

  if (phase === 'block') {
    return (
      <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fade-in">
        <div className="w-full max-w-sm rounded-[36px] bg-slate-900 border border-rose-500/40 p-6 text-center shadow-2xl relative overflow-hidden">
          <div className="absolute top-0 left-1/2 -translate-x-1/2 w-48 h-48 bg-rose-500/15 rounded-full blur-3xl pointer-events-none" />
          <div className="relative my-4 inline-flex items-center justify-center">
            <div className="w-16 h-16 rounded-full bg-rose-500/20 border-2 border-rose-400/40 flex items-center justify-center">
              <ShieldX className="w-8 h-8 text-rose-300" />
            </div>
          </div>
          <p className="text-xs uppercase tracking-wider font-bold text-rose-400">Blocked for your security</p>
          <h2 className="text-2xl font-black text-white font-heading mt-1">Payment not sent</h2>
          <p className="text-sm text-slate-300 mt-2">
            Sentinel blocked this transfer to {payeeName || 'payee'}. The transaction was not completed.
          </p>
          <p className="text-[11px] text-slate-500 mt-3 font-mono">
            {riskTier} · score {riskScore != null ? Number(riskScore).toFixed(3) : '—'}
          </p>
          <button
            onClick={close}
            className="w-full mt-6 py-3 rounded-2xl bg-rose-600 hover:bg-rose-500 text-white text-xs font-bold cursor-pointer"
          >
            Close
          </button>
        </div>
      </div>
    );
  }

  if (phase === 'error') {
    return (
      <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fade-in">
        <div className="w-full max-w-sm rounded-[36px] bg-slate-900 border border-slate-700 p-6 text-center shadow-2xl">
          <ShieldAlert className="w-10 h-10 text-slate-300 mx-auto mb-3" />
          <h2 className="text-lg font-bold text-white font-heading">Could not reach Sentinel</h2>
          <p className="text-sm text-slate-400 mt-2">Payment was not sent. Start the scoring API and try again.</p>
          <button
            onClick={close}
            className="w-full mt-6 py-3 rounded-2xl bg-slate-700 hover:bg-slate-600 text-white text-xs font-bold cursor-pointer"
          >
            Close
          </button>
        </div>
      </div>
    );
  }

  return null;
};
