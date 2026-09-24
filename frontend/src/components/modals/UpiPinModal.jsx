import React, { useState, useEffect } from 'react';
import { X, Delete, Shield, Fingerprint, Lock } from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { sound } from '../../utils/audio';

export const UpiPinModal = () => {
  const { upiPinModal, setUpiPinModal, user } = useApp();
  const { isOpen, amount, recipientName, purpose, onComplete, stepUp } = upiPinModal;

  const [pin, setPin] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const PIN_LENGTH = 4;

  useEffect(() => {
    if (isOpen) {
      setPin('');
      setIsProcessing(false);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleKeyPress = (digit) => {
    if (pin.length < PIN_LENGTH) {
      sound.playPinDigit();
      const newPin = pin + digit;
      setPin(newPin);

      // Auto submit when 4 digits reached
      if (newPin.length === PIN_LENGTH) {
        submitPin(newPin);
      }
    }
  };

  const handleDelete = () => {
    sound.playTap();
    setPin(prev => prev.slice(0, -1));
  };

  const handleBiometricAuth = () => {
    sound.playPinDigit();
    setIsProcessing(true);
    setTimeout(() => {
      submitPin("1234");
    }, 600);
  };

  const submitPin = (finalPin) => {
    setIsProcessing(true);
    setTimeout(() => {
      setUpiPinModal(prev => ({ ...prev, isOpen: false }));
      if (onComplete) {
        onComplete(finalPin);
      }
    }, 700);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/80 backdrop-blur-md animate-fade-in p-0 sm:p-4">
      <div className="w-full max-w-sm bg-slate-950 border border-slate-800 rounded-t-[36px] sm:rounded-3xl p-6 shadow-2xl relative text-center">
        {/* Cancel button */}
        <button
          onClick={() => setUpiPinModal({ isOpen: false, onComplete: null })}
          className="absolute top-5 right-5 p-2 rounded-full bg-slate-800/80 text-slate-400 hover:text-white cursor-pointer"
        >
          <X className="w-4 h-4" />
        </button>

        {/* Security badge & Header */}
        <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-blue-500/10 text-blue-400 text-xs font-semibold mb-3">
          <Lock className="w-3 h-3" />
          <span>{stepUp ? 'RE-CONFIRM UPI PIN' : 'ENTER UPI PIN'}</span>
        </div>

        <h3 className="text-xl font-bold text-white font-heading">
          {user.currency}{amount?.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
        </h3>
        <p className="text-xs text-slate-400 mt-0.5">
          {stepUp ? 'Step-up confirmation for' : 'Paying to'}{' '}
          <span className="text-white font-semibold">{recipientName}</span>
        </p>

        {/* PIN Indicators (4 Dots) */}
        <div className="flex justify-center items-center gap-4 my-6">
          {Array.from({ length: PIN_LENGTH }).map((_, index) => {
            const isFilled = index < pin.length;
            return (
              <div
                key={index}
                className={`w-4 h-4 rounded-full transition-all duration-200 ${
                  isFilled
                    ? 'bg-blue-500 scale-125 shadow-lg shadow-blue-500/50'
                    : 'bg-slate-800 border border-slate-700'
                }`}
              />
            );
          })}
        </div>

        {isProcessing && (
          <div className="text-xs text-blue-400 font-semibold animate-pulse mb-4 flex items-center justify-center gap-2">
            <span className="w-2 h-2 rounded-full bg-blue-400 animate-ping" />
            <span>Verifying Sentinel Encryption...</span>
          </div>
        )}

        {/* Numeric Keypad */}
        <div className="grid grid-cols-3 gap-3 max-w-[280px] mx-auto mb-4">
          {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((digit) => (
            <button
              key={digit}
              type="button"
              disabled={isProcessing}
              onClick={() => handleKeyPress(String(digit))}
              className="w-16 h-16 rounded-2xl bg-slate-900 hover:bg-slate-800 active:bg-blue-600/30 text-white font-heading font-semibold text-2xl mx-auto border border-slate-800 transition-all cursor-pointer shadow-sm active:scale-95"
            >
              {digit}
            </button>
          ))}

          {/* Biometric trigger */}
          <button
            type="button"
            disabled={isProcessing}
            onClick={handleBiometricAuth}
            className="w-16 h-16 rounded-2xl bg-slate-900/60 hover:bg-blue-600/20 text-blue-400 flex items-center justify-center mx-auto border border-slate-800 transition-all cursor-pointer"
            title="Authenticate with Touch/Face ID"
          >
            <Fingerprint className="w-7 h-7" />
          </button>

          {/* Zero */}
          <button
            type="button"
            disabled={isProcessing}
            onClick={() => handleKeyPress('0')}
            className="w-16 h-16 rounded-2xl bg-slate-900 hover:bg-slate-800 active:bg-blue-600/30 text-white font-heading font-semibold text-2xl mx-auto border border-slate-800 transition-all cursor-pointer shadow-sm active:scale-95"
          >
            0
          </button>

          {/* Backspace */}
          <button
            type="button"
            disabled={isProcessing}
            onClick={handleDelete}
            className="w-16 h-16 rounded-2xl bg-slate-900/60 hover:bg-rose-500/20 text-slate-400 hover:text-rose-400 flex items-center justify-center mx-auto border border-slate-800 transition-all cursor-pointer"
          >
            <Delete className="w-6 h-6" />
          </button>
        </div>

        {/* Security watermark footer */}
        <div className="pt-2 border-t border-slate-900 flex items-center justify-center gap-1.5 text-[10px] text-slate-400 font-medium">
          <Shield className="w-3 h-3 text-emerald-400" />
          <span>NPCI • UPI 2.0 • Sentinel Shield Protected</span>
        </div>
      </div>
    </div>
  );
};
