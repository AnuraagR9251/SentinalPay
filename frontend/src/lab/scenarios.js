/** Deterministic synthetic UPI-risk lab scenarios. Not bank or NPCI data. */

export const BLR = { lat: 12.9716, lon: 77.5946 };
export const DEL = { lat: 28.6139, lon: 77.209 };
/** Matches detection.graph_features.STRUCTURING_AMOUNT default. Experimental only. */
export const ENGINE_STRUCTURING_AMOUNT = 50000;
export const DEFAULT_DEMO_THRESHOLD = 50000;
export const LAB_HOME_DEVICE = 'lab-dev-home';
export const LAB_NEW_DEVICE = 'lab-dev-new';
export const KNOWN_PAYEE = 'kirana.lab@oksbi';

export const SCENARIO_DEFS = [
  {
    id: 'grocery',
    title: 'Normal known payee',
    blurb: 'Repeat grocery to a payee already in this synthetic history.',
  },
  {
    id: 'velocity',
    title: 'Five payments in five minutes',
    blurb: 'Four priors plus the live send, all inside the 5-minute velocity window.',
  },
  {
    id: 'location_device',
    title: 'New device + unusual location',
    blurb: 'Bengaluru GPS history, then a Delhi send on an unseen device.',
  },
  {
    id: 'below_threshold',
    title: 'Repeated below-threshold sends',
    blurb: 'Each payment is under the demo threshold; the combined total is over it.',
  },
  {
    id: 'new_payee',
    title: 'New payee, amount above baseline',
    blurb: 'Known small-ticket history, then a much larger first send to a stranger.',
  },
  {
    id: 'legit_high_freq',
    title: 'Legitimate high-frequency',
    blurb: 'Three known-payee groceries in five minutes — under the velocity rule.',
  },
  {
    id: 'missing_location',
    title: 'Missing location',
    blurb: 'No coordinates on history or the live send. Travel rules should stay quiet.',
  },
  {
    id: 'thin_history',
    title: 'Insufficient history',
    blurb: 'One prior row. Amount-anomaly needs three baselines and should not fire.',
  },
  {
    id: 'replay',
    title: 'Replay same transaction id',
    blurb: 'Submit the live send twice. Second call is an idempotent replay.',
  },
];

export function resolveLabUser({ scenarioId, runId, sessionUser, requireLogin }) {
  if (requireLogin && sessionUser) return sessionUser;
  return `lab.${scenarioId}.${runId}@sentinal.sim`;
}

export function belowThresholdUnit(threshold) {
  const cap = Number(threshold);
  if (!Number.isFinite(cap) || cap <= 0) return 100;
  return Math.max(100, Math.floor(cap / 3));
}

function stamp(now, msBefore) {
  return new Date(now.getTime() - msBefore).toISOString();
}

function row({
  userId,
  runId,
  tag,
  amount,
  merchantId,
  category,
  timestamp,
  deviceId,
  location,
}) {
  const out = {
    transactionId: `lab-${tag}-${runId}`,
    userId,
    amount,
    currency: 'INR',
    merchantId,
    merchantCategory: category,
    timestamp,
    deviceId,
    synthetic: true,
  };
  if (location && location.lat != null && location.lon != null) {
    out.latitude = location.lat;
    out.longitude = location.lon;
  }
  return out;
}

export function buildScenario(id, opts = {}) {
  const def = SCENARIO_DEFS.find((item) => item.id === id);
  if (!def) return null;
  const now = opts.now instanceof Date ? opts.now : new Date(opts.now || Date.now());
  const runId = String(opts.runId || now.getTime());
  const threshold = Number(opts.threshold > 0 ? opts.threshold : DEFAULT_DEMO_THRESHOLD);
  const userId = resolveLabUser({
    scenarioId: id,
    runId,
    sessionUser: opts.sessionUser,
    requireLogin: opts.requireLogin,
  });
  const isolatedUser = !(opts.requireLogin && opts.sessionUser);
  const unit = belowThresholdUnit(threshold);
  const limitations = [];
  if (!isolatedUser) {
    limitations.push(
      'Login is on, so this run reuses the signed-in user_id. Isolated lab users 403 on evaluateTransaction.'
    );
  }
  if (id === 'below_threshold' && unit * 4 <= ENGINE_STRUCTURING_AMOUNT) {
    limitations.push(
      `Combined synthetic total is ₹${unit * 4}. Experimental structuring_flag only trips above ₹${ENGINE_STRUCTURING_AMOUNT} (not blended).`
    );
  }
  if (id === 'grocery' || id === 'legit_high_freq') {
    limitations.push(
      'Uncalibrated PaySim P_xgb can still lift a legitimate send into REVIEW. That is a demo false-positive, not UPI accuracy.'
    );
  }

  const known = {
    userId,
    runId,
    merchantId: KNOWN_PAYEE,
    category: 'groceries',
    deviceId: LAB_HOME_DEVICE,
    location: BLR,
  };

  let history = [];
  let candidate;
  if (id === 'grocery') {
    const days = [14, 11, 8, 5, 2];
    const amounts = [220, 180, 260, 200, 240];
    history = days.map((day, i) =>
      row({ ...known, tag: `grocery-h${i}`, amount: amounts[i], timestamp: stamp(now, day * 86400000) })
    );
    candidate = row({ ...known, tag: 'grocery-live', amount: 240, timestamp: now.toISOString() });
  } else if (id === 'velocity') {
    history = [180, 120, 60, 30].map((sec, i) =>
      row({
        ...known,
        tag: `vel-h${i}`,
        amount: 400,
        merchantId: `burst${i}.lab@oksbi`,
        category: 'p2p_transfer',
        timestamp: stamp(now, sec * 1000),
      })
    );
    candidate = row({
      ...known,
      tag: 'vel-live',
      amount: 400,
      merchantId: 'burst-live.lab@oksbi',
      category: 'p2p_transfer',
      timestamp: now.toISOString(),
    });
  } else if (id === 'location_device') {
    history = [3 * 86400000, 2 * 86400000, 120000].map((ms, i) =>
      row({ ...known, tag: `geo-h${i}`, amount: 300, timestamp: stamp(now, ms) })
    );
    candidate = row({
      ...known,
      tag: 'geo-live',
      amount: 900,
      deviceId: LAB_NEW_DEVICE,
      location: DEL,
      category: 'p2p_transfer',
      merchantId: 'delhi.lab@oksbi',
      timestamp: now.toISOString(),
    });
  } else if (id === 'below_threshold') {
    history = [75, 50, 25].map((min, i) =>
      row({
        ...known,
        tag: `smurf-h${i}`,
        amount: unit,
        merchantId: `split${i}.lab@oksbi`,
        category: 'p2p_transfer',
        timestamp: stamp(now, min * 60000),
      })
    );
    candidate = row({
      ...known,
      tag: 'smurf-live',
      amount: unit,
      merchantId: 'split-live.lab@oksbi',
      category: 'p2p_transfer',
      timestamp: now.toISOString(),
    });
  } else if (id === 'new_payee') {
    history = [10, 8, 6, 4, 2].map((day, i) =>
      row({ ...known, tag: `base-h${i}`, amount: 200, timestamp: stamp(now, day * 86400000) })
    );
    candidate = row({
      ...known,
      tag: 'new-live',
      amount: 8000,
      merchantId: `stranger.${runId}@oksbi`,
      category: 'p2p_transfer',
      timestamp: now.toISOString(),
    });
  } else if (id === 'legit_high_freq') {
    history = [90, 40].map((sec, i) =>
      row({ ...known, tag: `freq-h${i}`, amount: 180, timestamp: stamp(now, sec * 1000) })
    );
    candidate = row({ ...known, tag: 'freq-live', amount: 180, timestamp: now.toISOString() });
  } else if (id === 'missing_location') {
    history = [3, 2, 1].map((day, i) =>
      row({
        ...known,
        tag: `nogeo-h${i}`,
        amount: 210,
        location: null,
        timestamp: stamp(now, day * 86400000),
      })
    );
    candidate = row({
      ...known,
      tag: 'nogeo-live',
      amount: 210,
      location: null,
      timestamp: now.toISOString(),
    });
  } else if (id === 'thin_history') {
    history = [row({ ...known, tag: 'thin-h0', amount: 200, timestamp: stamp(now, 86400000) })];
    candidate = row({
      ...known,
      tag: 'thin-live',
      amount: 9000,
      merchantId: `newthin.${runId}@oksbi`,
      category: 'p2p_transfer',
      timestamp: now.toISOString(),
    });
  } else if (id === 'replay') {
    history = [row({ ...known, tag: 'rep-h0', amount: 220, timestamp: stamp(now, 86400000) })];
    candidate = row({ ...known, tag: 'rep-live', amount: 220, timestamp: now.toISOString() });
  }

  const ids = [...history, candidate].map((item) => item.transactionId);
  return {
    id,
    title: def.title,
    blurb: def.blurb,
    synthetic: true,
    userId,
    isolatedUser,
    runId,
    threshold,
    unit,
    combinedBelowThreshold: id === 'below_threshold' ? unit * 4 : null,
    limitations,
    history,
    candidate,
    replay: id === 'replay',
    ids,
  };
}

export function assertHistoryBeforeCandidate(scenario) {
  const live = Date.parse(scenario.candidate.timestamp);
  for (const row of scenario.history) {
    if (!(Date.parse(row.timestamp) < live)) {
      throw new Error(`${row.transactionId} is not strictly before the live send`);
    }
  }
}
