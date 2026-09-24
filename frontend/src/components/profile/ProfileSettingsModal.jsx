import React from 'react';
import {
  X,
  Shield,
  ShieldCheck,
  Smartphone,
  Volume2,
  VolumeX,
  Moon,
  Sun,
  RotateCcw,
  CheckCircle2,
  Lock,
  ExternalLink,
  ChevronRight
} from 'lucide-react';
import { useApp } from '../../context/AppContext';

export const ProfileSettingsModal = () => {
  const {
    profileModal,
    setProfileModal,
    user,
    theme,
    setTheme,
    soundEnabled,
    setSoundEnabled,
    resetToDemo
  } = useApp();

  const { isOpen } = profileModal;

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fade-in">
      <div className="w-full max-w-sm rounded-[36px] bg-slate-900 border border-slate-700/80 p-6 shadow-2xl relative max-h-[90vh] overflow-y-auto no-scrollbar">
        {/* Close Button */}
        <button
          onClick={() => setProfileModal({ isOpen: false })}
          className="absolute top-5 right-5 p-2 rounded-full bg-slate-800 text-slate-400 hover:text-white cursor-pointer"
        >
          <X className="w-4 h-4" />
        </button>

        {/* Profile Card */}
        <div className="text-center pt-2 pb-4">
          <div className="relative inline-block mb-3">
            <img
              src={user.avatar}
              alt={user.name}
              className="w-20 h-20 rounded-3xl object-cover ring-4 ring-blue-500/30 mx-auto shadow-xl"
            />
            <div className="absolute -bottom-1 -right-1 p-1 rounded-full bg-blue-600 text-white ring-2 ring-slate-900">
              <CheckCircle2 className="w-4 h-4" />
            </div>
          </div>

          <h2 className="text-lg font-bold text-white font-heading">{user.name}</h2>
          <p className="text-xs text-blue-400 font-mono font-medium">{user.upiId}</p>
          <p className="text-[11px] text-slate-400 mt-0.5">{user.phone} • {user.email}</p>

          <div className="inline-flex items-center gap-1.5 mt-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs font-semibold">
            <ShieldCheck className="w-3.5 h-3.5" />
            <span>{user.kycStatus}</span>
          </div>
        </div>

        {/* Sentinel AI Shield Audit Card */}
        <div className="p-4 rounded-2xl bg-gradient-to-r from-blue-950/60 to-indigo-950/60 border border-blue-500/30 mb-4">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <Shield className="w-4 h-4 text-blue-400" />
              <span className="text-xs font-bold text-white">Sentinel AI Shield 2.0</span>
            </div>
            <span className="text-xs font-extrabold text-emerald-400">99.9% SECURE</span>
          </div>
          <p className="text-[11px] text-slate-300">
            End-to-end device tokenization, anti-phishing AI scan, and biometric encrypted vault are active.
          </p>
        </div>

        {/* Settings List */}
        <div className="space-y-2 mb-4">
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block px-1">
            Preferences & Security
          </span>

          {/* Sound Toggle */}
          <div className="p-3 rounded-2xl bg-slate-800/60 border border-slate-700/60 flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              {soundEnabled ? <Volume2 className="w-4 h-4 text-blue-400" /> : <VolumeX className="w-4 h-4 text-slate-400" />}
              <div>
                <p className="text-xs font-semibold text-white">Sound Effects</p>
                <p className="text-[10px] text-slate-400">UPI chimes & tactile haptics</p>
              </div>
            </div>
            <button
              onClick={() => setSoundEnabled(!soundEnabled)}
              className={`w-11 h-6 rounded-full transition-colors p-1 cursor-pointer flex items-center ${
                soundEnabled ? 'bg-blue-600 justify-end' : 'bg-slate-700 justify-start'
              }`}
            >
              <div className="w-4 h-4 rounded-full bg-white shadow-md" />
            </button>
          </div>

          {/* Theme Toggle */}
          <div className="p-3 rounded-2xl bg-slate-800/60 border border-slate-700/60 flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              {theme === 'dark' ? <Moon className="w-4 h-4 text-indigo-400" /> : <Sun className="w-4 h-4 text-amber-400" />}
              <div>
                <p className="text-xs font-semibold text-white">Interface Theme</p>
                <p className="text-[10px] text-slate-400">{theme === 'dark' ? 'Dark Mode' : 'Light Mode'}</p>
              </div>
            </div>
            <button
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              className="px-3 py-1 rounded-xl bg-slate-700 text-xs text-white font-medium hover:bg-slate-600 transition-colors cursor-pointer"
            >
              Toggle
            </button>
          </div>

          {/* Reset Demo Data */}
          <div className="p-3 rounded-2xl bg-slate-800/60 border border-slate-700/60 flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <RotateCcw className="w-4 h-4 text-rose-400" />
              <div>
                <p className="text-xs font-semibold text-white">Reset Demo Data</p>
                <p className="text-[10px] text-slate-400">Restore fresh mock balances</p>
              </div>
            </div>
            <button
              onClick={() => {
                if (confirm('Reset all demo transactions, scratch cards and balances to default?')) {
                  resetToDemo();
                  setProfileModal({ isOpen: false });
                }
              }}
              className="px-3 py-1 rounded-xl bg-rose-600/20 hover:bg-rose-600/30 text-rose-400 border border-rose-500/30 text-xs font-semibold transition-colors cursor-pointer"
            >
              Reset
            </button>
          </div>
        </div>

        {/* Version info */}
        <div className="text-center pt-2 border-t border-slate-800 text-[10px] text-slate-400">
          Senitenial Pay v1.0.0 (Production Build) • Inspired by Google Pay
        </div>
      </div>
    </div>
  );
};
