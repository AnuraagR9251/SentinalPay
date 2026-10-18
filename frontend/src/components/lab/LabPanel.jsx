import React, { useState } from 'react';
import { FlaskConical } from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { DEMO_PROFILES } from '../../data/mockData';

export const LabPanel = () => {
  const { user, switchDemoUser, runLabScenario, lastScore, sessionToken } = useApp();
  const [busy, setBusy] = useState(false);

  const run = async (id) => {
    setBusy(true);
    try {
      await runLabScenario(id);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-3xl border border-slate-700/80 bg-slate-800/40 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <FlaskConical className="w-4 h-4 text-emerald-400" />
        <h2 className="text-sm font-bold text-white font-heading">Sentinel lab</h2>
      </div>
      <p className="text-[11px] text-slate-400">
        Demo profile · {user.city || 'no city'} · {user.deviceId || 'no device'} · {sessionToken ? 'signed in' : 'open demo'}
      </p>
      <p className="text-[10px] text-slate-500">
        Location is sent only when the selected demo profile has coordinates. It is never filled in with a default city.
      </p>
      <div className="flex flex-wrap gap-2">
        {DEMO_PROFILES.map((profile) => (
          <button
            key={profile.id}
            type="button"
            onClick={() => switchDemoUser(profile.id)}
            className={`px-3 py-1.5 rounded-xl text-[11px] font-semibold border cursor-pointer ${
              user.upiId === profile.upiId
                ? 'bg-blue-600 text-white border-blue-500'
                : 'bg-slate-900 text-slate-300 border-slate-700'
            }`}
          >
            {profile.city} · {profile.name}
          </button>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-2">
        <button type="button" disabled={busy} onClick={() => run('grocery')} className="py-2 rounded-xl bg-slate-900 border border-slate-700 text-[11px] text-slate-200 cursor-pointer disabled:opacity-50">
          Normal grocery
        </button>
        <button type="button" disabled={busy} onClick={() => run('new_payee')} className="py-2 rounded-xl bg-slate-900 border border-slate-700 text-[11px] text-slate-200 cursor-pointer disabled:opacity-50">
          New payee + large
        </button>
        <button type="button" disabled={busy} onClick={() => run('velocity')} className="py-2 rounded-xl bg-slate-900 border border-slate-700 text-[11px] text-slate-200 cursor-pointer disabled:opacity-50">
          Velocity burst
        </button>
        <button type="button" disabled={busy} onClick={() => run('replay')} className="py-2 rounded-xl bg-slate-900 border border-slate-700 text-[11px] text-slate-200 cursor-pointer disabled:opacity-50">
          Replay same id
        </button>
      </div>
      {lastScore && (
        <p className="text-[11px] font-mono text-slate-400">
          {lastScore.canonical_decision || '—'} · {lastScore.risk_tier} · {Number(lastScore.risk_score).toFixed(3)}
          {lastScore.ae_available ? '' : ' · AE unavailable'}
          {lastScore.graph_available ? '' : ' · graph unavailable'}
          {lastScore.ml_available === false ? ' · model unavailable' : ''}
        </p>
      )}
    </section>
  );
};
