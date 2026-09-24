import React, { useState } from 'react';
import { X, Scale, ShieldCheck, RefreshCw, Lock, Check } from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { sound } from '../../utils/audio';

export const CheckBalanceModal = () => {
  const { checkBalanceModal, setCheckBalanceModal, banks, user } = useApp();
  const { isOpen, bank } = checkBalanceModal;

  const [selectedBank, setSelectedBank] = useState(bank || banks[0]);
  const [pinEntered, setPinEntered] = useState(false);
  const [pinDigits, setPinDigits] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  if (!isOpen) return null;

  const currentBank = selectedBank || banks[0];

  const handleKeyTap = (digit) => {
    if (pinDigits.length < 4) {
      sound.playPinDigit();
      const updated = pinDigits + digit;
      setPinDigits(updated);

      if (updated.length === 4) {
        setIsLoading(true);
        setTimeout(() => {
          setIsLoading(false);
          setPinEntered(true);
          sound.playSuccessChime();
        }, 600);
      }
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fade-in">
      <div className="w-full max-w-sm rounded-[36px] bg-slate-900 border border-slate-700/80 p-6 shadow-2xl relative text-center">
        {/* Close button */}
        <button
          onClick={() => {
            setCheckBalanceModal({ isOpen: false, bank: null });
            setPinEntered(false);
            setPinDigits('');
          }}
          className="absolute top-5 right-5 p-2 rounded-full bg-slate-800 text-slate-400 hover:text-white cursor-pointer"
        >
          <X className="w-4 h-4" />
        </button>

        {/* Bank selector pill */}
        <div className="flex items-center justify-center gap-2 mb-3">
          <div className="w-8 h-8 rounded-xl bg-blue-600/30 text-blue-400 flex items-center justify-center font-bold text-xs">
            {currentBank.logoText}
          </div>
          <div className="text-left">
            <h4 className="text-sm font-bold text-white">{currentBank.bankName}</h4>
            <p className="text-[10px] text-slate-400">{currentBank.accountNumber}</p>
          </div>
        </div>

        {!pinEntered ? (
          <div>
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-blue-500/10 text-blue-400 text-xs font-semibold mb-4">
              <Lock className="w-3.5 h-3.5" />
              <span>Enter 4-Digit UPI PIN</span>
            </div>

            <p className="text-xs text-slate-400 mb-4">
              Secure bank query encrypted via Sentinel Core
            </p>

            {/* PIN Dots */}
            <div className="flex justify-center gap-3 mb-6">
              {[0, 1, 2, 3].map((idx) => (
                <div
                  key={idx}
                  className={`w-3.5 h-3.5 rounded-full transition-all ${
                    idx < pinDigits.length
                      ? 'bg-blue-500 scale-125 shadow-md shadow-blue-500/50'
                      : 'bg-slate-800 border border-slate-700'
                  }`}
                />
              ))}
            </div>

            {isLoading ? (
              <div className="py-8 text-blue-400 text-xs font-semibold flex flex-col items-center gap-2">
                <RefreshCw className="w-6 h-6 animate-spin" />
                <span>Fetching live bank balance...</span>
              </div>
            ) : (
              <div className="grid grid-cols-3 gap-2.5 max-w-[240px] mx-auto mb-3">
                {[1, 2, 3, 4, 5, 6, 7, 8, 9, '', 0, 'del'].map((item, i) => {
                  if (item === '') return <div key={i} />;
                  if (item === 'del') {
                    return (
                      <button
                        key={i}
                        type="button"
                        onClick={() => {
                          sound.playTap();
                          setPinDigits(prev => prev.slice(0, -1));
                        }}
                        className="w-14 h-14 rounded-2xl bg-slate-800/80 text-slate-400 text-xs flex items-center justify-center font-bold cursor-pointer"
                      >
                        DEL
                      </button>
                    );
                  }
                  return (
                    <button
                      key={i}
                      type="button"
                      onClick={() => handleKeyTap(item)}
                      className="w-14 h-14 rounded-2xl bg-slate-800 hover:bg-slate-700 active:bg-blue-600/30 text-white font-heading font-semibold text-xl flex items-center justify-center mx-auto cursor-pointer shadow-sm active:scale-95"
                    >
                      {item}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        ) : (
          <div className="py-4 space-y-4">
            <div className="w-14 h-14 rounded-2xl bg-emerald-500/20 text-emerald-400 flex items-center justify-center mx-auto border border-emerald-500/30">
              <Check className="w-7 h-7" />
            </div>

            <div>
              <span className="text-xs text-slate-400 font-medium uppercase tracking-wider">
                Available Bank Balance
              </span>
              <div className="text-3xl font-black text-white font-heading mt-1">
                {user.currency}{currentBank.balance.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
              </div>
              <p className="text-[11px] text-slate-500 mt-1">
                A/C Type: {currentBank.accountType}
              </p>
            </div>

            <div className="p-3 rounded-2xl bg-slate-950 border border-slate-800 text-xs text-slate-400 flex items-center justify-between">
              <span>IFSC Code</span>
              <span className="font-mono text-slate-200">{currentBank.ifsc}</span>
            </div>

            <button
              onClick={() => {
                setCheckBalanceModal({ isOpen: false, bank: null });
                setPinEntered(false);
                setPinDigits('');
              }}
              className="w-full py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs shadow-lg shadow-blue-600/30 cursor-pointer"
            >
              Done
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
