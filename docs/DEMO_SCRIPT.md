# Demo Video Script (≤ 5 minutes)

**Setup before recording:**
- Follow the [README quick start](../README.md#run-the-demo-locally), run `python -m seed.seed` (fresh data) and start both servers.
- Set `VITE_DEMO_MODE=true` in `frontend/.env.local` so the sign-in page shows the demo account buttons.
- Set a 32+ character `SECRET_KEY` in `backend/.env` so a backend restart doesn't sign you out.
- Use a browser at 1440×900, light or dark theme.
- Close other tabs, and zoom to 110% for readability.

| Time | Screen | Action | Voice-over (suggested) |
|---|---|---|---|
| 0:00–0:20 | Login page | Show the page, click **Owner**, sign in | "Small-business owners make cash decisions without a CFO. SME Finance Copilot is an AI agent that analyses the business, forecasts cash, finds financing, and acts only with the owner's approval." |
| 0:20–0:55 | Dashboard | Point to the health score (60, *Fair*, weakest: liquidity), then the forecast chart's low point in late November below the dashed safety buffer, then the top alert | "Every number here comes from deterministic finance engines, not the language model. The forecast spots a cash squeeze six weeks out: payroll, a bulk flour order and the owner's draw all land in the same week." |
| 0:55–1:40 | Copilot | Type **"Can I afford a $45,000 oven in late November?"** and let it stream; point to the live tool timeline | "The agent chooses its own tools: forecast, what-if scenario, financing match. It says buying the oven outright would push cash to minus forty-two thousand, and recommends equipment financing instead." |
| 1:40–2:00 | Copilot (answer footer) | Point to **"8/8 figures verified"** and **"personal values hidden from AI"**; expand the tool trace | "Every figure in the answer is checked against the tool results. Names, emails and account numbers are masked before anything reaches the model, and the provider doesn't store the conversation." |
| 2:00–2:45 | Copilot | Ask **"Who owes me money? Remind the most overdue customer."**; the approval card appears; click **Approve**; the result says the reminder is ready in the outbox | "Actions are different. The agent can only create a request. Nothing is sent until a person approves it, here in one click. It also noticed a suspicious invoice memo telling the AI to move money, and ignored it." |
| 2:45–3:20 | Cash Flow | Tick **One-off purchase** ($45k, week 6) and **Take a loan** ($45k, 9.6%, 60 months), then **Run scenario**; show the scenario line vs. the baseline and the verdict | "Owners can test decisions themselves: buying with cash breaks the buffer, but financing keeps the business above zero." |
| 3:20–3:50 | Financing | **Compare** $45,000 / Equipment; show the #1 offer's score bars and reasons; open **Not available to you** to show the grant that could fund $25k | "Financing options are ranked by real cost, fit, approval odds, affordability and speed, and every excluded product says why." |
| 3:50–4:20 | Financing → Approvals | Click **Request application** on #1; on the card, approving without a password is refused; enter the password, approve, and the application reference appears | "High-value actions need the owner's password. Payments are capped at ten thousand dollars, and there's simply no tool that can move money to a new account." |
| 4:20–4:45 | Audit Log | Show **"Hash chain intact"**, filter to **Agent**, expand a record to show its hash and previous hash | "Every login, tool call and decision is in a hash-chained audit log. Edit or delete one record and verification pinpoints it." |
| 4:45–5:00 | Settings | Scroll the permissions-by-role table and the tool list | "Three permission tiers, human approval, verified numbers, private by design. That's AI as a financial participant you can trust." |

**Fallback:** if the network is unavailable, the copilot switches to offline mode automatically and the same flows still work, with templated answers.
