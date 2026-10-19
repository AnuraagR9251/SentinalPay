import React, { useState } from 'react';
import { Shield } from 'lucide-react';
import { useApp } from '../../context/AppContext';

export const LoginModal = () => {
  const { loginWithPassword, authError } = useApp();
  const [userId, setUserId] = useState('aarav@senitenial');
  const [password, setPassword] = useState('demo123');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await loginWithPassword(userId, password);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center p-4 bg-black/80 backdrop-blur-md">
      <form onSubmit={submit} className="w-full max-w-sm rounded-[28px] bg-slate-900 border border-slate-700 p-6 space-y-4">
        <div className="flex items-center gap-2">
          <Shield className="w-5 h-5 text-blue-400" />
          <h2 className="text-lg font-bold text-white font-heading">Sandbox sign-in</h2>
        </div>
        <p className="text-xs text-slate-400">
          Local demo credentials only — not a bank, UPI, or NPCI login. User <span className="font-mono">aarav@senitenial</span> / password <span className="font-mono">demo123</span> / sandbox PIN <span className="font-mono">1234</span>.
        </p>
        <input
          value={userId}
          onChange={(e) => setUserId(e.target.value)}
          className="w-full px-3 py-2 rounded-xl bg-slate-800 text-sm text-white border border-slate-700"
          placeholder="UPI ID"
        />
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full px-3 py-2 rounded-xl bg-slate-800 text-sm text-white border border-slate-700"
          placeholder="Password"
        />
        {authError && <p className="text-xs text-rose-400">{authError}</p>}
        <button
          type="submit"
          disabled={busy}
          className="w-full py-3 rounded-2xl bg-blue-600 text-white text-xs font-bold cursor-pointer disabled:opacity-50"
        >
          {busy ? 'Signing in…' : 'Continue'}
        </button>
      </form>
    </div>
  );
};
