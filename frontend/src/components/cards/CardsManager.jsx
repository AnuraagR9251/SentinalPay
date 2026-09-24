import React, { useState } from 'react';
import {
  CreditCard,
  Building2,
  Lock,
  Unlock,
  Eye,
  EyeOff,
  Plus,
  ShieldCheck,
  RefreshCw,
  CheckCircle2,
  Search,
  Wifi
} from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { POPULAR_BANKS_LIST } from '../../data/mockData';

export const CardsManager = () => {
  const {
    cards,
    toggleCardFreeze,
    banks,
    addBank,
    setCheckBalanceModal,
    user
  } = useApp();

  const [activeCardIndex, setActiveCardIndex] = useState(0);
  const [showCvv, setShowCvv] = useState(false);
  const [showAddBank, setShowAddBank] = useState(false);
  const [bankSearch, setBankSearch] = useState('');

  const currentCard = cards[activeCardIndex] || cards[0];

  const filteredBanksList = POPULAR_BANKS_LIST.filter(b =>
    b.toLowerCase().includes(bankSearch.toLowerCase())
  );

  return (
    <div className="space-y-6 max-w-4xl mx-auto px-4 py-4 animate-fade-in">
      {/* Header */}
      <div className="rounded-3xl p-6 bg-gradient-to-br from-slate-900 via-indigo-950 to-blue-950 border border-blue-500/20 shadow-xl flex items-center justify-between">
        <div>
          <span className="text-xs uppercase font-bold tracking-wider text-blue-400">
            Payment Instruments
          </span>
          <h1 className="text-2xl font-black text-white font-heading mt-1">
            Cards & Linked Banks
          </h1>
          <p className="text-xs text-slate-300 mt-1 max-w-md">
            Manage your UPI bank accounts, Rupay/Visa virtual cards, contactless limits, and instant lock settings.
          </p>
        </div>

        <button
          onClick={() => setShowAddBank(true)}
          className="flex items-center gap-2 px-4 py-2.5 rounded-2xl bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs shadow-lg shadow-blue-600/30 transition-all cursor-pointer whitespace-nowrap"
        >
          <Plus className="w-4 h-4" />
          <span>Add Bank</span>
        </button>
      </div>

      {/* Interactive Virtual Card Showcase */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-bold text-white font-heading">
            Senitenial Virtual Cards
          </h2>
          <div className="flex gap-1.5">
            {cards.map((c, i) => (
              <button
                key={c.id}
                onClick={() => setActiveCardIndex(i)}
                className={`w-2.5 h-2.5 rounded-full transition-all cursor-pointer ${
                  activeCardIndex === i ? 'bg-blue-500 w-6' : 'bg-slate-700'
                }`}
              />
            ))}
          </div>
        </div>

        {/* 3D Realistic Credit/Debit Card */}
        <div className="relative max-w-md mx-auto h-56 rounded-3xl p-6 shadow-2xl overflow-hidden transition-all duration-300 select-none group border border-slate-700/80 bg-gradient-to-tr from-slate-950 via-slate-900 to-indigo-950">
          {/* Card background glowing accents */}
          <div className="absolute top-0 right-0 -mr-8 -mt-8 w-40 h-40 rounded-full bg-blue-500/10 blur-2xl pointer-events-none" />

          {/* Frozen Overlay */}
          {currentCard.isFrozen && (
            <div className="absolute inset-0 bg-slate-950/80 backdrop-blur-sm z-20 flex flex-col items-center justify-center text-rose-400">
              <Lock className="w-10 h-10 mb-2 animate-bounce" />
              <p className="text-sm font-bold uppercase tracking-wider">Card Temporarily Frozen</p>
              <p className="text-xs text-slate-400 mt-0.5">Transactions are blocked for security</p>
            </div>
          )}

          {/* Card Top */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-lg font-black tracking-wider text-white font-heading">
                SENITENIAL
              </span>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-300 font-semibold border border-blue-500/30">
                {currentCard.variant}
              </span>
            </div>
            <Wifi className="w-5 h-5 text-slate-400 rotate-90" />
          </div>

          {/* Chip */}
          <div className="mt-4 mb-2 flex items-center gap-3">
            <div className="w-11 h-8 rounded-lg bg-gradient-to-tr from-amber-300 via-yellow-400 to-amber-500 border border-amber-600/40 shadow-inner flex items-center justify-center">
              <div className="w-8 h-5 border border-amber-800/30 rounded-sm opacity-50" />
            </div>
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
          </div>

          {/* Card Number */}
          <div className="my-2">
            <p className="font-mono text-xl sm:text-2xl font-bold tracking-widest text-slate-100 drop-shadow">
              {currentCard.cardNumber}
            </p>
          </div>

          {/* Card Bottom: Holder Name, Expiry & CVV */}
          <div className="mt-2 flex items-center justify-between text-xs text-slate-300">
            <div>
              <span className="text-[9px] text-slate-400 uppercase tracking-wider block">Card Holder</span>
              <p className="font-semibold tracking-wide uppercase">{currentCard.name}</p>
            </div>

            <div className="flex items-center gap-4">
              <div>
                <span className="text-[9px] text-slate-400 uppercase tracking-wider block">Expires</span>
                <p className="font-mono font-semibold">{currentCard.expiry}</p>
              </div>

              <div>
                <span className="text-[9px] text-slate-400 uppercase tracking-wider block">CVV</span>
                <p className="font-mono font-semibold">
                  {showCvv ? currentCard.cvv : '•••'}
                </p>
              </div>
            </div>

            <span className="text-sm font-black italic tracking-wider text-white">
              {currentCard.type}
            </span>
          </div>
        </div>

        {/* Card Controls */}
        <div className="max-w-md mx-auto mt-4 grid grid-cols-2 gap-2">
          <button
            onClick={() => toggleCardFreeze(currentCard.id)}
            className={`py-2.5 px-4 rounded-2xl border text-xs font-semibold flex items-center justify-center gap-2 transition-all cursor-pointer ${
              currentCard.isFrozen
                ? 'bg-emerald-600/20 text-emerald-400 border-emerald-500/40 hover:bg-emerald-600/30'
                : 'bg-rose-600/20 text-rose-400 border-rose-500/40 hover:bg-rose-600/30'
            }`}
          >
            {currentCard.isFrozen ? <Unlock className="w-4 h-4" /> : <Lock className="w-4 h-4" />}
            <span>{currentCard.isFrozen ? 'Unfreeze Card' : 'Freeze Card'}</span>
          </button>

          <button
            onClick={() => setShowCvv(!showCvv)}
            className="py-2.5 px-4 rounded-2xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-semibold flex items-center justify-center gap-2 transition-all cursor-pointer"
          >
            {showCvv ? <EyeOff className="w-4 h-4 text-blue-400" /> : <Eye className="w-4 h-4 text-blue-400" />}
            <span>{showCvv ? 'Hide CVV' : 'View CVV'}</span>
          </button>
        </div>
      </div>

      {/* Linked Bank Accounts */}
      <div className="space-y-3">
        <h2 className="text-base font-bold text-white font-heading">
          Linked UPI Bank Accounts ({banks.length})
        </h2>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {banks.map((bank) => (
            <div
              key={bank.id}
              className="p-4 rounded-2xl bg-slate-800/50 border border-slate-700/70 hover:border-slate-600 transition-all flex flex-col justify-between"
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-blue-600/20 text-blue-400 flex items-center justify-center font-bold text-xs border border-blue-500/30">
                    {bank.logoText}
                  </div>
                  <div>
                    <div className="flex items-center gap-1.5">
                      <h3 className="text-sm font-bold text-white">{bank.bankName}</h3>
                      {bank.isPrimary && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-blue-500/20 text-blue-300 font-semibold">
                          PRIMARY
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-slate-400">{bank.accountType} • {bank.accountNumber}</p>
                    <p className="text-[10px] text-slate-500 font-mono">IFSC: {bank.ifsc}</p>
                  </div>
                </div>
              </div>

              <div className="mt-4 pt-3 border-t border-slate-700/50 flex items-center justify-between">
                <div>
                  <span className="text-[10px] text-slate-400">Account Balance</span>
                  <div className="text-base font-black text-white font-heading">
                    {user.currency}{bank.balance.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                  </div>
                </div>

                <button
                  onClick={() => setCheckBalanceModal({ isOpen: true, bank })}
                  className="px-3 py-1.5 rounded-xl bg-blue-500/10 hover:bg-blue-500/20 border border-blue-500/30 text-blue-400 text-xs font-semibold flex items-center gap-1 transition-all cursor-pointer"
                >
                  <RefreshCw className="w-3 h-3" />
                  <span>Check Balance</span>
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Add Bank Modal */}
      {showAddBank && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-3xl bg-slate-900 border border-slate-700/80 p-6 shadow-2xl">
            <h3 className="text-lg font-bold text-white mb-1 font-heading">Link Bank Account</h3>
            <p className="text-xs text-slate-400 mb-4">Select your bank to fetch accounts linked with {user.phone}</p>

            <div className="relative mb-3">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
              <input
                type="text"
                placeholder="Search bank name..."
                value={bankSearch}
                onChange={(e) => setBankSearch(e.target.value)}
                className="w-full pl-9 pr-3 py-2 rounded-xl bg-slate-800 border border-slate-700 text-xs text-white focus:outline-none focus:border-blue-500"
              />
            </div>

            <div className="space-y-1.5 max-h-56 overflow-y-auto mb-4 pr-1">
              {filteredBanksList.map((bName) => (
                <button
                  key={bName}
                  onClick={() => {
                    addBank(bName);
                    setShowAddBank(false);
                    setBankSearch('');
                  }}
                  className="w-full p-2.5 rounded-xl bg-slate-800/80 hover:bg-blue-600/20 hover:border-blue-500/40 border border-slate-700/60 text-left text-xs font-medium text-slate-200 hover:text-white flex items-center justify-between cursor-pointer transition-all"
                >
                  <span className="truncate">{bName}</span>
                  <Plus className="w-3.5 h-3.5 text-blue-400" />
                </button>
              ))}
            </div>

            <button
              onClick={() => setShowAddBank(false)}
              className="w-full py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold cursor-pointer"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
