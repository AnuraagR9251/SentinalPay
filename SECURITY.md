# Security boundary

SentinalPay is a CSE7102 sandbox. It scores simulated UPI-like payments. It is not a bank, not a payment processor, and not production fraud infrastructure.

## Data this system handles

- Synthetic PaySim rows and demo React seed data. Treat statement CSVs as sensitive even when synthetic.
- Logs mask identifiers (`transaction_id`, last-four of VPAs). Do not log PINs, passwords, or webhook secrets.
- Training artefacts store numeric features and metrics only.
- `dataset/`, `*.csv`, `*.xlsx`, `*.pkl`, and `ml/artifacts/` are gitignored.

## Controls that are implemented

- Config via environment variables. `.env` is gitignored. `.env.example` has placeholders only.
- Optional API key (`SENTINALPAY_API_KEY`) gates REST and GraphQL score/evaluate/feed/reviews/PIN when set. Optional login (`SENTINALPAY_REQUIRE_LOGIN=1`) requires a bearer session on those routes **and** on review list/submit. Open scoring is demo-only; `/health` reports `open_sandbox` and `auth_warning`. Set `SENTINALPAY_REQUIRE_LOGIN=1` before any gateway keys.
- **Review queue has no reviewer/admin role** (intentional sandbox limit, not a missing check). With login on, any valid demo session can list and decide pending reviews. With login off and no API key, the queue is open. Keep the API on localhost; do not expose reviews on a shared network.
- Sessions are stored as SHA-256 hashes with `expires_at` (default 12h). `POST /logout` (and GraphQL `logout`) revokes the presented token. Client-only `localStorage` clear does not revoke the server session. Login failures are rate-limited per user+IP.
- Demo password/PIN hashes (PBKDF2) in SQLite. Demo login `aarav@senitenial` / `demo123` / PIN `1234` is sandbox only.
- Parameterized SQL in `risk.store` (SQLite default; Postgres if `SENTINALPAY_DATABASE_URL` is set).
- HTTP 429 on score/evaluate/feed/PIN via `risk.auth` (Redis when `SENTINALPAY_REDIS_URL` works; otherwise in-process per worker). Payment velocity stays in `risk.security` / rules and does not return 429.
- Idempotent persist on `transaction_id`.
- Model load failures use a 0.5 prior and demote ALLOW → REVIEW. The prior is never returned as `model_probability`.
- STEP_UP challenges: short-lived, attempt-capped, replay-protected, labeled sandbox PIN (not bank OTP).
- Razorpay TEST webhooks: HMAC-SHA256 on the exact raw bytes, unique `event_id`, stale/future events rejected. Body size is counted while reading the ASGI stream (`SENTINALPAY_WEBHOOK_MAX_BYTES`, default 64KiB, HTTP 413). That is not a substitute for a reverse-proxy limit (`client_max_body_size` / equivalent). Browser redirects are never treated as paid. Order creation is never anonymous: `REQUIRE_LOGIN=1` needs a session (and the API key if configured). Service-to-service exception: `REQUIRE_LOGIN=0` plus a valid API key may create an order with no session. Challenge IDs are omitted from the public feed.

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
