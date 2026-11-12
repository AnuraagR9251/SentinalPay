import React, { useEffect, useState } from 'react';
import { ShieldAlert, ShieldCheck, ShieldX, LoaderCircle, Clock3 } from 'lucide-react';
import { fetchHoldAssessment, holdView, remainingSeconds } from '../../api/holdAssessment';
import { SECONDARY_COPY, formatDecisionLine } from '../../api/scoreDisplay';
import { useApp } from '../../context/AppContext';

export const RiskGateModal = () => {
  const { riskGateModal, setRiskGateModal, user, sessionToken } = useApp();
  const { isOpen, phase, riskTier, payeeName, amount, canonicalDecision, message, onContinue, pXgb, canonicalRiskScore, mlCalibrated, transactionId, deadline, reasons } = riskGateModal;
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!isOpen || phase !== 'hold') return undefined;
    const clock = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(clock);
  }, [isOpen, phase, deadline]);

  useEffect(() => {
    if (!isOpen || phase !== 'hold' || !transactionId) return undefined;
    let cancel = false;
    const headers = sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {};
    const poll = async () => {
      try {
        const row = await fetchHoldAssessment(transactionId, headers);
        if (cancel) return;
        const view = holdView(row);
        setRiskGateModal((prev) => ({ ...prev, ...view, onContinue: prev.onContinue, transactionId }));
      } catch {
        if (!cancel) {
          setRiskGateModal((prev) => ({
            ...prev,
            phase: 'error',
            message: 'Security assessment could not be confirmed. Payment was not completed.',
          }));
        }
      }
    };
    poll();
    const timer = setInterval(poll, 1000);
    return () => {
      cancel = true;
      clearInterval(timer);
    };
  }, [isOpen, phase, transactionId, sessionToken, setRiskGateModal]);

  if (!isOpen) return null;

  const secondsLeft = deadline ? remainingSeconds(deadline, now) : null;

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
          <p className="text-[11px] text-slate-500 mt-4">Demo risk engine — scoring is not a bank payment.</p>
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
          <p className="text-xs uppercase tracking-wider font-bold text-amber-400">Pending security assessment</p>
          <h2 className="text-2xl font-black text-white font-heading mt-1">
            {user.currency}{Number(amount || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
          </h2>
          <p className="text-4xl font-black text-amber-200 font-heading mt-3">
            {secondsLeft == null ? '—' : `${secondsLeft}s`}
          </p>
          <p className="text-sm text-slate-300 mt-2">
            {message || SECONDARY_COPY.PENDING}
          </p>
          {reasons && reasons.length ? (
            <p className="text-[11px] text-slate-400 mt-2">{reasons.join(', ')}</p>
          ) : null}
          <p className="text-[11px] text-slate-500 mt-3 font-mono">
            {formatDecisionLine({
              canonicalDecision: canonicalDecision || 'REVIEW',
              riskTier,
              canonicalRiskScore: canonicalRiskScore,
              pXgb: pXgb,
              mlCalibrated: mlCalibrated,
            })}
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

  if (phase === 'cleared') {
    return (
      <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fade-in">
        <div className="w-full max-w-sm rounded-[36px] bg-slate-900 border border-emerald-500/40 p-6 text-center shadow-2xl relative overflow-hidden">
          <div className="absolute top-0 left-1/2 -translate-x-1/2 w-48 h-48 bg-emerald-500/15 rounded-full blur-3xl pointer-events-none" />
          <div className="relative my-4 inline-flex items-center justify-center">
            <div className="w-16 h-16 rounded-full bg-emerald-500/20 border-2 border-emerald-400/40 flex items-center justify-center">
              <ShieldCheck className="w-8 h-8 text-emerald-300" />
            </div>
          </div>
          <p className="text-xs uppercase tracking-wider font-bold text-emerald-400">Checks passed</p>
          <h2 className="text-2xl font-black text-white font-heading mt-1">
            {user.currency}{Number(amount || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
          </h2>
          <p className="text-sm text-slate-300 mt-2">
            {message || SECONDARY_COPY.ALLOW}
          </p>
          <button
            onClick={() => {
              const go = onContinue;
              close();
              if (go) go();
            }}
            className="w-full mt-6 py-3 rounded-2xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold cursor-pointer"
          >
            Continue to payment
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
            {message || `Sentinel blocked this transfer to ${payeeName || 'payee'}. The transaction was not completed.`}
          </p>
          <p className="text-[11px] text-slate-500 mt-3 font-mono">
            {formatDecisionLine({
              canonicalDecision: canonicalDecision || 'BLOCK',
              riskTier,
              canonicalRiskScore: canonicalRiskScore,
              pXgb: pXgb,
              mlCalibrated: mlCalibrated,
            })}
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

  if (phase === 'limited') {
    return (
      <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fade-in">
        <div className="w-full max-w-sm rounded-[36px] bg-slate-900 border border-slate-700 p-6 text-center shadow-2xl">
          <Clock3 className="w-10 h-10 text-amber-300 mx-auto mb-3" />
          <h2 className="text-lg font-bold text-white font-heading">Scoring paused briefly</h2>
          <p className="text-sm text-slate-400 mt-2">
            Too many requests. Payment was not sent. Wait a moment, then try again.
          </p>
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

  if (phase === 'error') {
    return (
      <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fade-in">
        <div className="w-full max-w-sm rounded-[36px] bg-slate-900 border border-slate-700 p-6 text-center shadow-2xl">
          <ShieldAlert className="w-10 h-10 text-slate-300 mx-auto mb-3" />
          <h2 className="text-lg font-bold text-white font-heading">Could not reach Sentinel</h2>
          <p className="text-sm text-slate-400 mt-2">{message || 'Payment was not sent. Start the scoring API and try again.'}</p>
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
