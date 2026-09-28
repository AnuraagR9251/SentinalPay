# SentinalPay

UPI fraud-risk API for CSE7102. Phase 1 unifies scoring behind one engine.

## Current API

| Endpoint | Contract | Status |
|---|---|---|
| `POST /score` | Legacy React body. Returns 0–1 `risk_score` and `ALLOW` / `HOLD` / `BLOCK` | **Implemented** (adapter) |
| `POST /api/v1/transactions/evaluate` | Canonical 0–100 `risk_score` and `ALLOW` / `REVIEW` / `BLOCK` | **Implemented** |
| `GET /health` | `{status, model_loaded}` | **Implemented** |
| `GET /transactions` | Desk feed from SQLite | **Implemented** |
| `POST /api/v1/reviews/{id}` | Analyst approve/reject | **Implemented** (basic) |

## What is actually running

| Piece | Status |
|---|---|
| Canonical engine `risk/` | **Implemented** |
| SQLite (`SENTINALPAY_DATABASE_URL`, default `data/sentinalpay.db`) | **Implemented** |
| In-process velocity / rate-limit cache | **Implemented** |
| XGBoost inference (`ml/models/xgboost_model.pkl`) | **Experimental** — synthetic geo leak; not production-grade |
| Aggregation weights `rules 0.25 / behavior 0.25 / ml 0.40 / security 0.10` | **Implemented** |
| React app talking to `POST /score` | **Implemented** |
| Streamlit desk on a simulated stream | **Implemented** (separate from the live API) |
| PostgreSQL | **Planned** — not implemented |
| Redis | **Planned** — not implemented |
| SHAP | **Planned** — not implemented |
| Logistic Regression / Random Forest | **Planned** — not implemented |
| Docker Compose / AWS | **Planned** — not implemented |

## Architecture

```
React App
    ↓
POST /score                         POST /api/v1/transactions/evaluate
    ↓                                          ↓
api/compat.py (format only)              api/v1.py (canonical JSON)
    ↓                                          ↓
              risk.pipeline.evaluate_transaction()
                              ↓
         Security → Rules → Behavior → ML (experimental XGBoost)
                              ↓
                      risk.aggregate
                              ↓
              0–100 score + ALLOW / REVIEW / BLOCK
                              ↓
                      risk.store (SQLite)
```

`detection/` remains for the Streamlit simulator and feature extraction. It does **not** decide the live `/score` result.

### Legacy `/score` mapping (adapter only)

| Canonical | Frontend |
|---|---|
| ALLOW | ALLOW |
| REVIEW | HOLD |
| BLOCK | BLOCK |

`STEP_UP` is not fabricated from `REVIEW`. A real step-up policy belongs in a later action layer.

## Setup

Python 3.10+ (developed against 3.11).

```bash
py -3 -m pip install -r requirements.txt
copy .env.example .env
py -3 -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Frontend: `VITE_SCORE_API_URL` (default `http://localhost:8000`) then `npm run dev` in `frontend/`.

`.env` is gitignored. See [SECURITY.md](SECURITY.md).

## Tests

```bash
py -3 -m pytest
```

## Project layout

```
api/main.py          HTTP + /score adapter
api/compat.py        canonical → legacy UI fields
api/v1.py            versioned evaluate / review
risk/pipeline.py     orchestrates evaluation
risk/aggregate.py    0–100 score + ALLOW/REVIEW/BLOCK
risk/store.py        SQLite persistence + idempotency
detection/           legacy desk + feature helpers
ml/models/           experimental XGBoost artefact
frontend/            React UPI demo
dashboard/           Streamlit simulator
```

## Out of scope this phase

PostgreSQL, Redis, Docker Compose, SHAP, extra classifiers, merchant fraud-rate models, analyst retraining, AWS.
