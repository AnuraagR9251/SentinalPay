import React, { useState } from 'react';
import { Gift, Sparkles, Award, ArrowRight, Share2, Copy, Check } from 'lucide-react';
import { useApp } from '../../context/AppContext';

export const RewardsPreview = () => {
  const { rewards, setScratchCardModal } = useApp();
  const [showReferralModal, setShowReferralModal] = useState(false);
  const [copied, setCopied] = useState(false);

  // Compute total cashback won
  const totalCashback = rewards
    .filter(r => r.isScratched && r.type === 'cashback')
    .reduce((sum, r) => sum + r.amount, 450);

  const unscratchedCards = rewards.filter(r => !r.isScratched);
  const scratchedCards = rewards.filter(r => r.isScratched);

  const handleCopyCode = () => {
    navigator.clipboard?.writeText('SENITENIAL-REWARDS-AARAV');
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <section className="py-2">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-amber-500/20 text-amber-400">
            <Gift className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-base font-bold text-white tracking-tight font-heading">
              Rewards & Offers
            </h2>
          </div>
        </div>

        <button
          onClick={() => setShowReferralModal(true)}
          className="text-xs text-amber-400 hover:text-amber-300 font-semibold flex items-center gap-1 cursor-pointer"
        >
          <span>Invite & Earn ₹101</span>
          <ArrowRight className="w-3 h-3" />
        </button>
      </div>

      {/* Rewards Banner */}
      <div className="rounded-2xl p-4 bg-gradient-to-r from-amber-600/20 via-orange-600/20 to-purple-600/20 border border-amber-500/30 mb-3 flex items-center justify-between">
        <div>
          <span className="text-[11px] font-semibold uppercase tracking-wider text-amber-300">
            Total Rewards Won
          </span>
          <div className="text-2xl font-extrabold text-white font-heading">
            ₹{totalCashback.toLocaleString('en-IN')}
          </div>
          <p className="text-xs text-slate-300 mt-0.5">
            {unscratchedCards.length > 0
              ? `${unscratchedCards.length} scratch card${unscratchedCards.length > 1 ? 's' : ''} waiting to be scratched!`
              : 'Keep paying with Senitenial Pay to win more!'}
          </p>
        </div>

        <div className="relative">
          <div className="w-14 h-14 rounded-2xl bg-amber-500/20 border border-amber-400/40 flex items-center justify-center animate-bounce">
            <Award className="w-7 h-7 text-amber-400" />
          </div>
        </div>
      </div>

      {/* Scratch Cards Carousel */}
      <div className="flex gap-3 overflow-x-auto no-scrollbar pb-1">
        {/* Unscratched Cards first */}
        {unscratchedCards.map((reward) => (
          <div
            key={reward.id}
            onClick={() => setScratchCardModal({ isOpen: true, reward })}
            className="flex-shrink-0 w-36 h-44 rounded-2xl bg-gradient-to-br from-indigo-700 via-purple-700 to-pink-600 p-[2px] shadow-lg shadow-purple-900/30 cursor-pointer group hover:scale-105 transition-all"
          >
            <div className="w-full h-full bg-slate-900/90 rounded-[14px] p-3 flex flex-col items-center justify-between text-center relative overflow-hidden">
              <div className="absolute top-0 right-0 w-16 h-16 bg-white/5 rounded-full blur-xl pointer-events-none" />

              <span className="px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 text-[10px] font-bold tracking-wide uppercase border border-amber-400/30 animate-pulse">
                Scratch to Win
              </span>

              <div className="my-auto">
                <Sparkles className="w-8 h-8 text-amber-400 mx-auto group-hover:rotate-12 transition-transform" />
                <p className="text-xs font-bold text-white mt-2 leading-tight">
                  Surprise Reward
                </p>
              </div>

              <span className="text-[10px] text-slate-400">
                Tap & scratch
              </span>
            </div>
          </div>
        ))}

        {/* Scratched Cards */}
        {scratchedCards.map((reward) => (
          <div
            key={reward.id}
            onClick={() => setScratchCardModal({ isOpen: true, reward })}
            className="flex-shrink-0 w-36 h-44 rounded-2xl bg-slate-800/80 border border-slate-700/80 p-3 flex flex-col justify-between cursor-pointer hover:border-slate-600 transition-all"
          >
            <div className="flex items-center justify-between">
              <span className="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 text-[9px] font-bold">
                CLAIMED
              </span>
              <Award className="w-4 h-4 text-emerald-400" />
            </div>

            <div className="my-auto text-center">
              <div className="text-2xl font-black text-emerald-400 font-heading">
                {reward.type === 'cashback' ? `₹${reward.amount}` : `${reward.amount}%`}
              </div>
              <p className="text-xs font-semibold text-white mt-1 line-clamp-1">
                {reward.title}
              </p>
            </div>

            <span className="text-[10px] text-slate-400 text-center">
              {reward.scratchedAt || 'Claimed'}
            </span>
          </div>
        ))}
      </div>

      {/* Referral Modal */}
      {showReferralModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-3xl bg-slate-900 border border-slate-700/80 p-6 shadow-2xl text-center">
            <div className="w-14 h-14 rounded-2xl bg-amber-500/20 text-amber-400 flex items-center justify-center mx-auto mb-3">
              <Gift className="w-7 h-7" />
            </div>

            <h3 className="text-xl font-bold text-white mb-1 font-heading">
              Invite Friends, Earn ₹101
            </h3>
            <p className="text-xs text-slate-300 mb-4">
              Get ₹101 cashback in your Senitenial Wallet when your friend completes their first UPI payment!
            </p>

            <div className="flex items-center justify-between p-3 rounded-2xl bg-slate-800 border border-slate-700 mb-4">
              <div className="text-left">
                <span className="text-[10px] uppercase text-slate-400 font-bold">Your Referral Code</span>
                <p className="text-sm font-mono font-bold text-amber-400">SENITENIAL-REWARDS-AARAV</p>
              </div>
              <button
                onClick={handleCopyCode}
                className="p-2 rounded-xl bg-slate-700 hover:bg-slate-600 text-white cursor-pointer transition-colors"
              >
                {copied ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
              </button>
            </div>

            <button
              onClick={() => setShowReferralModal(false)}
              className="w-full py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-medium text-xs shadow-lg shadow-blue-600/30 transition-all cursor-pointer"
            >
              Done
            </button>
          </div>
        </div>
      )}
    </section>
  );
};
