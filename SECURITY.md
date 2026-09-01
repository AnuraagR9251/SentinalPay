# Security boundary (academic phase)

SentinalPay is a CSE7102 mini-project. This file states what the system handles today and what it **does not** implement, so a reviewer should not infer production readiness from the engineering style of the scoring code.

## Data this system handles

- **Synthetic simulator traffic** plus locally stored training files under `dataset/` (PaySim public research log, a UPI statement CSV, a small xlsx). The UPI CSV can resemble real spend — treat it as PII even if it is synthetic.
- Those fields are still treated as **sensitive financial PII** in code: the scoring engine logs only `transaction_id`, `score`, and the ML class name. VPAs, phones, and device IDs are masked (last four characters) if they must appear in a diagnostic string.
- Training artefacts store **numeric features and metrics only** — never merchant names, VPAs, or PaySim `nameOrig` / `nameDest`.
- The Streamlit desk shows payee and amount for demo explainability. That display is not a log sink.
- `dataset/`, `*.csv`, `*.xlsx`, and `ml/artifacts/` are gitignored.

## Controls that are implemented

- No secrets or credentials in source. Configuration is via environment variables (`python-dotenv`); `.env` is gitignored; `.env.example` contains placeholders only.
- Scoring input is validated. Negative / non-numeric amounts, missing required fields, and out-of-range coordinates raise `ScoringValidationError` instead of being coerced.
- `score_transaction` is stateless and does not mutate caller-supplied history.
- Dataset-like artefacts (`dataset/`, `*.csv`, `*.xlsx`, `ml/artifacts/`) are gitignored so a later dump cannot be committed by accident.

## Explicitly out of scope (not implemented)

| Control | Status |
|---|---|
| Authentication / authorisation on the dashboard or any API | Not implemented |
| TLS / transport encryption | Not implemented |
| Encryption at rest | Not implemented |
| Real PII ingestion, retention, or deletion workflows | Not implemented |
| Rate limiting | Not implemented — `# TODO` markers sit at the future HTTP boundary |
| Database access | Not implemented — any future persistence **must** use parameterized queries or an ORM, never string-formatted SQL |
| Production VPN/proxy intelligence (commercial IP feeds) | Demo CIDRs + optional `SENTINALPAY_VPN_CIDRS` only |

The FastAPI adapter, when added, must apply rate limiting **before** calling `score_transaction` and must not log raw transaction bodies.

## Honest boundary

This phase demonstrates scoring correctness, input hygiene, and PII-aware logging on synthetic data. It is not a deployable payments-security product.
