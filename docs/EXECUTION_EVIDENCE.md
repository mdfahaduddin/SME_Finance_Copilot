# Execution Evidence

The competition asks non-on-chain topics for **simulated-account/sandbox operation logs** and a demo video. Everything here was produced by running the real application against its sandbox: the synthetic bakery ledger, a newly registered business, a mock lender marketplace and a simulated outbox. No real money or messages moved.

Generated on 2026-10-13 with the live AI (`gpt-6-luna`). **37 of 37 steps behaved as expected; 229 backend tests and 42 frontend tests passed** (7 OCR tests are skipped on machines without Tesseract, including CI; the Docker image includes Tesseract).

## Files

| File | What it shows |
|---|---|
| [evidence/operation_log.md](evidence/operation_log.md) | A 37-step scripted session through the real API. Part 1, the demo bakery: sign-in, dashboard, four copilot conversations, the human approval flow, guardrail refusals, a prompt-injection attempt. Part 2, production flows: a new business registering in taka, CSRF protection, a PDF bank statement checked and imported, isolation between businesses, currency-aware limits and financing, two-factor sign-in, brute-force limiting and report downloads (the lender PDF and an Excel export). Then audit verification and tamper detection. Each step records the actor, request, HTTP status, expected outcome, timing and result |
| [evidence/operation_log.json](evidence/operation_log.json) | The same log in machine-readable form, including every agent tool call, the groundedness result and the number of personal values masked |
| [evidence/audit_log.json](evidence/audit_log.json) | Export of the demo business's hash-chained audit log from that session, with its verification proof (`chain.valid`, `headHash`) |
| [evidence/outbox.json](evidence/outbox.json) | What the sandbox prepared after human approval: the customer payment reminder and the lender application |
| [evidence/test_report.txt](evidence/test_report.txt) | Verbose pytest run (backend): every test and its result |
| [evidence/frontend_test_report.txt](evidence/frontend_test_report.txt) | Verbose Vitest run (frontend): sign-in and two-factor, sidebar, conversation search/pin/rename/delete, toasts, form fields, report periods, downloads, currency formatting |

## What the session demonstrates

| Requirement | Steps |
|---|---|
| The agent completes real tasks: analysis, forecast, affordability, financing, action requests | 3–6, 10 |
| Every figure comes from the engines ("figures verified": 6/6, 8/8, 1/1) | The groundedness line on each copilot step |
| Personal data is masked before the AI | The "PII values masked" count on each copilot step |
| Human-in-the-loop: the agent requests, a person approves, once | 6 (nothing sent yet), 7–9 |
| Step-up authentication for high-value approvals | 12–13 |
| Permission tiers and hard limits | 7, 14–17 |
| Prompt-injection resistance | 18 (direct attempt, refused). In step 6 the agent itself flags the planted invoice memo that tells the AI to move money |
| Self-service onboarding in the business's own currency | 19, 21 |
| Cookie sessions require a CSRF token for changes | 20 |
| PDF bank statement: every row reconciled against the printed running balance, categorised, safe to re-import | 22–24 |
| Businesses cannot see each other's data | 25 |
| Safety limits and financing criteria converted into the business currency (BDT) | 26–27 |
| Two-factor authentication (TOTP) | 28–32 |
| Password guessing is rate-limited | 33 |
| Reports: lender-ready PDF summary and a viewer's Excel export, both audited | 34–35 |
| Tamper-evident audit log | 36–37 |

## Reproduce it

```bash
cd backend
python -m scripts.generate_evidence --tests     # live AI if OPENAI_API_KEY is set, otherwise offline mode
python -m scripts.generate_evidence --offline   # fully deterministic, no network
```

The script builds a fresh database (`backend/data/evidence.db`, never the demo database) with data as of 2026-10-13, so the figures are reproducible. In offline mode the copilot's answers come from the rule-based router; every other step is identical. The script exits non-zero if any step doesn't behave as expected.

## Demo video

The 5-minute walkthrough follows [DEMO_SCRIPT.md](DEMO_SCRIPT.md). Link: *to be added before submission*.
