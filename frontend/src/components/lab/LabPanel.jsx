import React, { useState } from 'react';
import { FlaskConical } from 'lucide-react';
import { formatDecisionLine } from '../../api/scoreDisplay';
import { useApp } from '../../context/AppContext';
import { DEFAULT_DEMO_THRESHOLD, ENGINE_STRUCTURING_AMOUNT, SCENARIO_DEFS } from '../../lab/scenarios';

const CANONICAL_NOTE =
  'Canonical decision uses rules + behavior + xgb_v3 + security. Autoencoder, graph score, and structuring_flag are experimental and not blended.';

export const LabPanel = () => {
  const { user, sessionToken, requireLogin, runLabScenario, lastLab } = useApp();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [threshold, setThreshold] = useState(DEFAULT_DEMO_THRESHOLD);

  const run = async (id) => {
    setBusy(true);
    setError('');
    try {
      await runLabScenario(id, { threshold: Number(threshold) || DEFAULT_DEMO_THRESHOLD });
    } catch (err) {
      setError(err?.message || 'Lab evaluate failed');
    } finally {
      setBusy(false);
    }
  };

  const result = lastLab?.candidate;
  const scenario = lastLab?.scenario;
  const rules = result?.rules?.triggered_rules || [];
  const experimental = result?.experimental || {};

  return (
    <section className="rounded-3xl border border-slate-700/80 bg-slate-800/40 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <FlaskConical className="w-4 h-4 text-emerald-400" />
        <h2 className="text-sm font-bold text-white font-heading">UPI risk simulation lab</h2>
      </div>
      <p className="text-[11px] text-amber-200/90">
        Synthetic simulation only. Records, cities, and devices are generated here. This does not touch UPI rails, bank
        accounts, or collect a PIN/OTP.
      </p>
      <p className="text-[10px] text-slate-500">{CANONICAL_NOTE}</p>
      <p className="text-[10px] text-slate-500">
        {requireLogin && sessionToken
          ? `Login is on — evaluateTransaction must use ${user.upiId}. Isolated lab users are disabled.`
          : 'Open sandbox — each run uses a fresh lab.*@sentinal.sim user so history stays resettable.'}
      </p>
      <label className="block text-[11px] text-slate-300">
        Demo below-threshold cap (₹)
        <input
          type="number"
          min={200}
          step={100}
          value={threshold}
          onChange={(event) => setThreshold(event.target.value)}
          className="mt-1 w-full rounded-xl bg-slate-900 border border-slate-700 px-3 py-1.5 text-slate-100"
        />
      </label>
      <p className="text-[10px] text-slate-500">
        Engine experimental structuring_flag still uses ₹{ENGINE_STRUCTURING_AMOUNT}. A lower demo cap will not invent a
        canonical structuring rule.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {SCENARIO_DEFS.map((item) => (
          <button
            key={item.id}
            type="button"
            disabled={busy}
            onClick={() => run(item.id)}
            className="text-left px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-[11px] text-slate-200 cursor-pointer disabled:opacity-50"
          >
            <span className="block font-semibold text-white">{item.title}</span>
            <span className="block text-slate-500">{item.blurb}</span>
          </button>
        ))}
      </div>
      {busy && <p className="text-[11px] text-slate-400">Scoring synthetic history, then the live send…</p>}
      {error && <p className="text-[11px] text-rose-300">{error}</p>}
      {result && scenario && (
        <div className="space-y-2 rounded-2xl border border-slate-700 bg-slate-950/70 p-3">
          <p className="text-[10px] uppercase tracking-wide text-emerald-400">Synthetic result · {scenario.title}</p>
          <p className="text-[11px] font-mono text-slate-300">
            {formatDecisionLine({
              canonicalDecision: result.canonical_decision,
              riskTier: result.risk_tier,
              canonicalRiskScore: result.canonical_risk_score,
              pXgb: result.P_xgb,
              mlCalibrated: result.ml_calibrated_for_upi,
            })}
          </p>
          <p className="text-[11px] text-slate-300">
            Policy action <span className="font-semibold text-white">{result.action || '—'}</span>
            {' · '}
            Model {result.ml_available ? 'available (PaySim xgb_v3, not UPI-calibrated)' : 'unavailable'}
            {' · '}
            Location baseline {result.location_baseline || 'UNKNOWN'}
          </p>
          {result.idempotent && <p className="text-[11px] text-sky-300">Replay: same transaction_id returned the stored result.</p>}
          <div>
            <p className="text-[10px] font-semibold text-slate-400">Canonical rules</p>
            {rules.length === 0 ? (
              <p className="text-[11px] text-slate-500">No triggered rules.</p>
            ) : (
              <ul className="text-[11px] text-slate-200 space-y-1">
                {rules.map((item) => (
                  <li key={`${item.rule}-${item.reason}`}>
                    <span className="font-semibold">{item.rule}</span>
                    {item.reason ? ` — ${item.reason}` : ''}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="rounded-xl border border-dashed border-violet-500/50 p-2">
            <p className="text-[10px] font-semibold text-violet-300">Experimental — not in the ALLOW/REVIEW/BLOCK blend</p>
            <p className="text-[11px] text-slate-400">
              graph {experimental.graph_available ? 'available' : 'unavailable'}
              {experimental.P_graph == null ? '' : ` · P_graph ${Number(experimental.P_graph).toFixed(3)}`}
              {' · '}
              structuring_flag {String(experimental.structuring_flag)}
              {' · '}
              AE {experimental.ae_available ? 'available' : 'unavailable'}
              {experimental.P_ae == null ? '' : ` · P_ae ${Number(experimental.P_ae).toFixed(3)}`}
            </p>
            <p className="text-[10px] text-slate-500">{experimental.note || CANONICAL_NOTE}</p>
          </div>
          {scenario.id === 'below_threshold' && (
            <p className="text-[11px] text-slate-400">
              Combined synthetic total ₹{scenario.combinedBelowThreshold} vs demo cap ₹{scenario.threshold} (each ₹
              {scenario.unit}).
            </p>
          )}
          {scenario.limitations.map((line) => (
            <p key={line} className="text-[10px] text-amber-200/80">
              {line}
            </p>
          ))}
          <p className="text-[10px] text-slate-600">
            User {scenario.userId} · seeded {scenario.history.length} prior rows · live {scenario.candidate.transactionId}
          </p>
        </div>
      )}
    </section>
  );
};
