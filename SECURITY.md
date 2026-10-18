# Security boundary

SentinalPay is a CSE7102 sandbox. It scores simulated UPI-like payments. It is not a bank, not a payment processor, and not production fraud infrastructure.

## Data this system handles

- Synthetic PaySim rows and demo React seed data. Treat statement CSVs as sensitive even when synthetic.
- Logs mask identifiers (`transaction_id`, last-four of VPAs). Do not log PINs, passwords, or webhook secrets.
- Training artefacts store numeric features and metrics only.
- `dataset/`, `*.csv`, `*.xlsx`, `*.pkl`, and `ml/artifacts/` are gitignored.

## Controls that are implemented

- Config via environment variables. `.env` is gitignored. `.env.example` has placeholders only.
- Optional API key (`SENTINALPAY_API_KEY`) and optional login (`SENTINALPAY_REQUIRE_LOGIN`).
- Demo password/PIN hashes (PBKDF2) in SQLite. Demo login `aarav@senitenial` / `demo123` / PIN `1234` is sandbox only.
- Parameterized SQL in `risk.store` (SQLite default; Postgres if `SENTINALPAY_DATABASE_URL` is set).
- Per-client request rate notes in `risk.security` (in-process or Redis).
- Idempotent persist on `transaction_id`.
- Model load failures use a 0.5 prior and demote ALLOW → REVIEW. The prior is never returned as `model_probability`.
- STEP_UP challenges: short-lived, attempt-capped, replay-protected, labeled sandbox PIN (not bank OTP).
- Razorpay TEST webhooks: HMAC-SHA256. Browser redirects are never treated as paid.

## Fail-open vs fail-closed

- Missing/broken XGBoost: fail-closed on ALLOW (REVIEW). Independent BLOCK rules still fire.
- Risk service down: a gateway must **not** skip Razorpay/auth. This engine is advisory.
- STEP_UP challenge: fail-closed — do not execute until the bound challenge succeeds.
- Unwired AE/graph: null, not zero.

## Explicitly out of scope

- TLS, encryption at rest, production IAM
- Real card/PAN/CVV/UPI PIN/OTP collection
- NPCI or bank connectivity
- Vetoing Razorpay authorization
- Certified fraud detection or production-ready ML (PaySim evaluation only)

## Retention

Local SQLite under `data/` is a demo store. There is no deletion workflow. Do not load real customer payments.
