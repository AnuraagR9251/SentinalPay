# SentinalPay

Machine-learning-oriented UPI fraud detection (CSE7102). This milestone ships a **stateless behavioural + location scoring engine** and a **Streamlit analyst dashboard** fed by a synthetic transaction stream.

The scoring function is a pure function of `(transaction, history, user_profile)` so a later FastAPI layer can call it concurrently without race conditions.

## Architecture

```
transaction + history + profile
        │
        ▼
score_transaction()          ← public API (detection/)
   ├── behavioural features  (amount z-score, new payee, velocity, recency)
   ├── location features     (haversine, implied speed, VPN/proxy CIDR)
   └── ML purpose-risk       (XGBoost: LEGIT / SUSPICIOUS / LIKELY_FRAUD)
        │
        ▼
RiskAssessment { score 0–1, action: Legit | Step-up | Hold | Block }
        │
        ▼
Streamlit desk  ← SimulatedStream today
                ← HttpTransactionSource later (same protocol)
```

## Setup

Python 3.10+ (developed against 3.11).

```bash
py -3 -m pip install -r requirements.txt
copy .env.example .env
```

`.env` is gitignored. See [SECURITY.md](SECURITY.md) for what this system does and does not protect.

## Tests

```bash
py -3 -m pytest
```

Coverage includes a clean payment (Allow), an account-takeover pattern (Block), impossible travel, a new user with no history, missing coordinates, input validation, history immutability, PII-safe logging, and ML feature/inference checks.

## Train the payment-risk model

Place the datasets under `dataset/` (gitignored):

- `PS_20174392719_1491204439457_log.csv` — PaySim, the only hard `isFraud` labels
- `upi_transactions_2025.csv` — UPI statement with **purpose/category**; weakly labeled
- `upi_digital_payment_dataset.xlsx` — demographics / spending category only (no y)

```bash
py -3 -m ml.train
```

This writes `ml/artifacts/payment_risk_xgb.json` and holdout metrics. Classes:

| Label | Meaning |
|---|---|
| LEGIT | Everyday merchant / salary / small UPI |
| SUSPICIOUS | Large P2P or cash-out, failed UPI, category outlier |
| LIKELY_FRAUD | PaySim `isFraud=1` (full-balance TRANSFER/CASH_OUT) |

The rule score is unchanged; the ML class is attached so an analyst can see both.

## Dashboard

```bash
py -3 -m streamlit run dashboard/app.py
```

The feed is generated in-process by `dashboard.data_simulator.SimulatedStream` (~80% clean, ~20% fraud: account takeover, velocity burst, structuring, impossible travel). Pause the live feed, inspect a row, and read the feature breakdown.

To point the UI at a future API, change `_init_state` in `dashboard/app.py` to construct `HttpTransactionSource(base_url=...)`. Do not import `detection.features` from the dashboard.

## Project layout

```
detection/scoring_engine.py   public score_transaction
detection/ml_classifier.py    XGBoost inference wrapper
detection/features/           behavioural + location extractors
detection/tests/              pytest suite
ml/train.py                   3-class model trainer
dashboard/app.py              Streamlit desk
dashboard/data_simulator.py   TransactionSource protocol + simulator
dataset/                      local only — never commit
```

## Out of scope this phase

FastAPI routes, autoencoder / NetworkX, React, and authentication. Thresholds live in `detection/constants.py`.
