# SentinalPay

UPI fraud-risk API for CSE7102. One engine (`risk.pipeline.evaluate_transaction`). GraphQL and REST are adapters. This is a sandbox, not a bank.

## Current API

| Endpoint | Contract | Status |
|---|---|---|
| `POST /score` | Legacy React body. 0–1 score + ALLOW / STEP_UP / HOLD / BLOCK | **Implemented** (adapter + policy) |
| `POST /api/v1/transactions/evaluate` | Canonical 0–100 + ALLOW / REVIEW / BLOCK | **Implemented** |
| `POST /login` | Demo password session | **Implemented** |
| `POST /pin/verify` | Demo UPI PIN or bound STEP_UP challenge | **Implemented** (sandbox, not bank OTP) |
| `GET /health` | `{status, model_loaded, model_version, ml_fallback, ae_loaded, ae_error}` | **Implemented** |
| `GET /ready` | Store reachable; missing model still ready | **Implemented** |
| `GET /transactions` | Nested sandbox feed: `payment` / `canonical` / `policy` / `models` | **Implemented** |
| `POST /graphql` | Same engine as REST (`scoreTransaction`, `evaluateTransaction`, `login`) | **Implemented** |
| `POST /webhooks/razorpay` | HMAC-signed TEST webhooks | **Implemented** (no live calls without keys) |

## What is actually running

| Piece | Status |
|---|---|
| Canonical engine `risk/` | **Implemented** |
| SQLite (default) | **Implemented** |
| Honest XGBoost `xgb_v3` | **Experimental** — synthetic PaySim eval, chrono 60/20/20, vs rules+LR |
| Missing-model fallback | **Implemented** — prior 0.5, ALLOW demoted to REVIEW |
| AE / graph on `/score` | **Experimental signals** — not blended into ALLOW / REVIEW / BLOCK. Missing AE is `null`, not 0 |
| Demo lab in the React app | **Implemented** |
| Login / PIN / STEP_UP policy | **Implemented** (local demo hashes + bound sandbox challenge) |
| ATO heuristic | **Implemented** — `ATO_SUSPECTED` only with two corroborating rules; not a trained model |
| Postgres / Redis | **Implemented** when URL env vars are set; SQLite + in-process cache remain the default |
| GraphQL (`/graphql`) | **Implemented** — adapter only, not a second scorer |
| Razorpay TEST adapter | **Implemented** — signature + state machine; live REST only if keys are set |
| Bank / NPCI connectivity | **Not implemented** (needs authorized partnership) |
| SHAP / extra classifiers / AWS | **Out of scope** |

## Architecture

```
React demo (lab + optional login)
    ↓
POST /graphql  (scoreTransaction)  or  REST /score /evaluate
    ↓
risk.pipeline.evaluate_transaction()
    ↓
Security → Rules (+ ATO heuristic) → Behavior → XGBoost (xgb_v3)
    + experimental AE / graph (reported, not blended)
    ↓
ALLOW / REVIEW / BLOCK
    ↓
policy_action()  →  ALLOW / STEP_UP / HOLD / BLOCK
    ↓
RiskStore (SQLite or Postgres) + optional sandbox STEP_UP challenge
```

`STEP_UP` is not a rename of `REVIEW`. It fires on REVIEW plus a new merchant or device, then a short-lived sandbox PIN challenge bound to that transaction.

Evaluate aliases (additive): `model_probability` (null unless the model actually ran), `model_available`, `triggered_signals`, `reason_codes`, `policy_version`, `inference_latency_ms`.

`fraud_probability` is the model P(fraud) including the 0.5 prior when the model is down. `model_probability` is **null** in that case. `risk_score` is the 0–100 blend. Demo cutovers on **risk_score** (env): 0–29 ALLOW, 30–69 REVIEW, 70–100 BLOCK. Starting values only.

Razorpay TEST mode is advisory. This service cannot veto authorization. A browser redirect is never payment success.

Training eval is **synthetic PaySim** (chrono 60/20/20, vs rules + logistic regression, precision-recall / review catch vs extra reviews). No labeled UPI holdout was available. Drain/CASH_OUT flags are not ML features.

If the XGBoost file is missing, the engine does **not** treat ML as 0. It uses a conservative prior of 0.5 (40% layer → 20 points) and will not return ALLOW. `GET /health` reports `model_loaded`, `ml_fallback`, `open_sandbox`, and `auth_warning`. Default `SENTINALPAY_REQUIRE_LOGIN=0` is an open local sandbox; an API key is not end-user authentication. When `SENTINALPAY_API_KEY` is set, REST and GraphQL score/evaluate/feed/reviews/PIN require `X-API-Key`. Set `SENTINALPAY_REQUIRE_LOGIN=1` to bind REST and GraphQL score/evaluate to the session user. HTTP 429 uses `SENTINALPAY_HTTP_RATE_LIMIT_PER_MIN` (in-process unless Redis is configured).

Identical retries with the same `transaction_id` and the same user/amount/currency/merchant return the stored result (one audit row). Reusing that ID with different material fields is HTTP 409 and does not leak the original score.

Utility bills stay unpaid until sandbox payment completion (ALLOW, or STEP_UP after PIN). Opening the payment modal, HOLD, BLOCK, cancel, or a failed score does not mark a bill Paid.

Razorpay TEST webhooks verify the raw body HMAC and dedupe on `X-Razorpay-Event-Id` (payload `id` if the header is absent). Duplicate or older events do not rewind payment state.

`P_ae` and `P_graph` on `/score` are experimental. They do not change ALLOW / REVIEW / BLOCK. Missing autoencoder → `P_ae: null` and `ae_available: false` (never a silent 0.0). Graph scores a 24h window from SQLite (capped 2000 rows), built per request, not an in-memory durable graph. `P_hybrid` on `/score` remains the canonical 0–100 score mapped to 0–1.

Demo lab GPS is per profile (Bengaluru / Delhi), labeled simulated — not device coordinates.

## Setup

```bash
py -3 -m pip install -r requirements.txt
copy .env.example .env
py -3 -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir api --reload-dir risk --reload-dir dashboard --reload-dir payments
```

Open GraphiQL in the browser at:

```
http://127.0.0.1:8000/graphql
```

REST `/score`, `/login`, and `/pin/verify` stay.

Demo login (sandbox only, not a bank account): `aarav@senitenial` / `demo123` / PIN `1234`. Sessions expire (default 12h) and are stored hashed. Set `SENTINALPAY_REQUIRE_LOGIN=1` before enabling Razorpay keys. SentinalPay is not a real payment processor.

Frontend: `npm run dev` in `frontend/`. Set `VITE_REQUIRE_LOGIN=1` to show the login gate.

Run the sandbox together (three terminals from the repo root):

```bash
py -3 -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir api --reload-dir risk --reload-dir dashboard --reload-dir payments
cd frontend && npx vite --host 127.0.0.1 --port 5173
py -3 -m streamlit run dashboard/app.py
```

The desk polls `GET /transactions` only. It does not switch to the unused `SimulatedStream`. React balances, UTRs, and rewards are local sandbox values — ALLOW is not a bank settlement.

Retrain the model after changing features **only if the PaySim CSV is already on disk** (not committed; can be hundreds of MB):

```bash
py -3 ml/train_xgboost.py
```

The repo tracks a small `ml/models/xgboost_model.pkl` (PaySim **xgb_v3**) so a clean checkout can load the model. `GET /health` must show `model_loaded: true` on the machine you present from. The autoencoder `.keras` is optional and may be present locally; if it is missing, `/health` reports `ae_loaded: false`. PaySim CSV and other `*.pkl` files stay gitignored. Retrain only if that CSV is already local.

## Tests

```bash
py -3 -m pytest
```

Postgres idempotency runs only when `SENTINALPAY_TEST_POSTGRES` is set.
