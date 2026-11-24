# Valor user guide

How to set up Valor, run a review end to end, and work as an analyst or a reviewer. For the architecture and
how to swap in real data, see the [README](../README.md).

> Prototype: all borrowers, deals, figures and policy limits are mock. Nothing here is a credit decision.

---

## 1. Set up

### What you need

| | |
|---|---|
| Python | 3.11 or later (`python3 --version`) |
| Claude Code CLI | Optional but recommended. Valor calls it in headless mode for the agent features. Check with `claude --version`. On a bank laptop it should already be configured for the bank's AWS Bedrock account; if `claude -p "hello"` answers, Valor can use it. |
| A browser | Chrome, Edge, Safari or Firefox |

Without the Claude CLI, Valor still works fully: the agent features fall back to deterministic rules
(set `VALOR_AGENT_MODE=mock` to force this).

### Install

```bash
cd valor
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

### Load demo cases (optional)

```bash
.venv/bin/python scripts/seed_demo_cases.py
```

This creates three cases:

| Case | Borrower | Workflow | State |
|---|---|---|---|
| VAL-2026-0001 | Ironvale Manufacturing | Troubled | Approved and locked |
| VAL-2026-0002 | Harbor Point Logistics | Performing | Submitted, waiting for a reviewer |
| VAL-2026-0003 | Bluepeak Software | Performing | Draft |

### Start the app

```bash
.venv/bin/python -m valor                       # then open http://127.0.0.1:8050
```

If port 8050 is taken, choose another: `VALOR_PORT=8070 .venv/bin/python -m valor`.

To stop it, press `Ctrl+C` in the terminal.

### Check it works

```bash
.venv/bin/python -m pytest -q                   # expect "28 passed"
```

---

## 2. Find your way around

- **Top bar:** Cases (home), New case, Engine, the agent mode (`agent: claude` or `agent: mock`), and
  **Acting as**. Acting as stands in for single sign-on: pick who you are. Analysts (Avery Chen, Jordan Okafor)
  prepare reviews; reviewers (Morgan Reyes, Sam Patel) check and approve them.
- **Home:** one card per case, showing value, variance to the first line, status and opinion. Use the chips to
  filter by Needs action, In review or Approved. **Click a card** to see its details and jump into the case.
- **Inside a case:** the header shows the borrower, status, the traffic light and the opinion, with exposure,
  the first line's value, the second line's value and (for troubled deals) the reserve. The menu on the left lists
  the eight steps: ✓ means done, an amber number means something to do there.
- **Throughout:**
  - Hover or tab to an **ⓘ** to see sources and explanations.
  - **Click any card marked ↗** to open its detail; press Esc to close.
  - **Next →** at the bottom of each step takes you on.

---

## 3. Key ideas

| Term | What it means here |
|---|---|
| First line / second line | The first line (the deal team) values the business; the second line (you) independently reviews that valuation. |
| Add-backs | Items management adds to reported EBITDA (one-off costs, expected savings, synergies). The first line usually takes management's "adjusted EBITDA". |
| Normalized EBITDA | Reported EBITDA plus the share of each add-back you accept. Every multiple-based value uses it. |
| Methods | Performing: DCF, trading comparables, precedent transactions. Troubled: liquidation analysis, distressed going concern. Each gives a low–high range; weights reconcile them. |
| Loan-to-value (LTV) | (Debt ranking ahead of the bank + bank commitment) ÷ enterprise value. Policy limit: 60%, or 75% in the downside case. |
| Coverage | (Enterprise value − debt ahead of the bank) ÷ bank commitment. Policy minimum: 1.5x. |
| Downside case | Every method re-run with EBITDA −20%, multiples −1.0x and discount rate +1pt. |
| Specific reserve | Troubled deals: bank exposure − present value of the expected recovery (discounted at the loan's rate). |
| Traffic light | Variance of your value to the first line's: green within 5%, amber 5–15%, red above 15%. |
| Opinion | Concur, Concur with exceptions (with conditions), or Do not concur. |

Policy limits and defaults are placeholders in `config/settings.yaml`.

---

## 4. Walkthrough: analyst

Act as **Avery Chen · analyst**. Start a new case, or open Bluepeak Software (draft).

1. **New case.** Choose the valuation request. The workflow is suggested from the deal's risk status
   (Performing or Troubled). Then **Create case**.
2. **Scope.**
   - Press **Pull data**. Valor loads the deal, financials, projections, add-backs, claims and market data.
   - Review the first line's package: their EBITDA, multiple, WACC, growth.
   - Browse the pulled tables in the tabs. **CSV** downloads one table; **Download all (.xlsx)** gives every table
     plus an Inputs sheet listing each input's source.
3. **Earnings.**
   - The bridge shows reported EBITDA, each add-back, and your normalized EBITDA against management's figure.
   - Click an add-back's percentage to change how much of it you accept. Give a reason; it goes to the audit trail.
   - The Haircut figure shows how much value the difference is worth at the peer multiple.
4. **Assumptions.**
   - Your changes sit at the top. Below is the workbench, one section per group (projections, cash flow,
     discount rate, multiples, exposure, downside shocks, weights).
   - Click **Adjust**, or a Y1–Y5 cell, to change a value; a rationale is required. Source values stay visible.
   - Press **Run valuation** when done.
5. **Valuation.** Read it top to bottom:
   - Headline numbers.
   - **How the value is built:** click a method card for its workings, such as the DCF projection and sensitivity, or
     the peer set.
   - **What it means for the loan:** click the downside or policy cards for headroom; for troubled deals, the reserve
     and claims stack.
   - **Agent commentary:** written automatically after each run; allow 15–20 s with Claude.
   - **Review checks.**
   - **What-if:** try values without saving anything.
6. **Challenge.**
   - Compare the first line's assumptions with yours, row by row.
   - Press **Ask the agent** for recommendations, then Accept, Edit or Reject each one. Edit and Reject need a
     reason.
   - Accepted changes become normal audited adjustments. Re-run the valuation afterwards.
7. **Opinion.**
   - The rules suggest a verdict. **Draft with agent** writes a rationale, conditions, top risks and questions
     for the first line.
   - Edit it, choose the verdict, and press **Save opinion**.
   - If you re-run the valuation later, save the opinion again.
8. **Approval.**
   - The checklist shows what is still missing: a current valuation, decided recommendations, answered
     challenges, and an opinion on the latest run.
   - Add a note and **Submit**. The case is then frozen while it is reviewed.
9. **Deliver.**
   - Choose a template (full memo, one-page summary or slides) and press **Generate**. Untick "agent narrative"
     for a faster report without a Claude call.
   - Download .docx, open the HTML and print it to PDF, or download Markdown.
   - **Share** pre-fills a Gmail draft for you to edit and send yourself. Valor never sends email.

---

## 5. Walkthrough: reviewer

Act as **Morgan Reyes · reviewer** and open Harbor Point Logistics (In review).

1. Read the case: Valuation, Challenge (the first line vs second line table), Opinion, and the Audit trail.
2. **Challenge an assumption** (link in the yellow bar, or on the Approval step).
   - It opens **What-if** on the Valuation step. Pick an assumption, enter a value and press **Try it**.
     Stack as many as you like.
   - The comparison shows the effect on value, LTV, coverage or reserve, the traffic light, policy breaches and the
     suggested verdict. Nothing is saved.
3. Decide on the Approval step:
   - **Approve and lock:** the case becomes read-only.
   - **Send back** with a comment, or **Send back with these challenges** from What-if. Each challenge records the
     analyst's value, your value, its impact and your reason.

You can't approve a case you submitted. Analysts can't approve at all.

### When a case comes back (analyst)

The red bar says "Answer N challenge(s) →". On the Challenge step:
- **Accept reviewer value** applies it as an audited adjustment.
- **Decline with response** requires a written reason.

Then re-run the valuation, re-save the opinion and resubmit.

---

## 6. Troubled deals

Open Ironvale Manufacturing. The flow is the same, but the methods are liquidation analysis and distressed
going concern, and both run through a **recovery waterfall** by creditor class.
- The result is the bank's recovery, discounted to present value, and the **specific reserve**.
- Adjust asset recovery rates, the claims stack, time to recovery and the discount rate on the Assumptions step.

---

## 7. The audit trail

Every case has an **Audit trail** (bottom of the step menu). It records every data pull, input change (old and
new values, source value, who, when, why), valuation run, agent call, recommendation and decision, challenge,
opinion, submission, approval and report.
- The log can only be appended to. Each entry is chained to the previous one, and "Chain verified" confirms nothing
  has been altered.
- Filter it by Inputs, Runs, Agent or Workflow, or download it with **Export CSV**.

---

## 8. Troubleshooting

| Problem | Fix |
|---|---|
| "Port 8050 is in use" | Start with another port: `VALOR_PORT=8070 .venv/bin/python -m valor` |
| Buttons or cards don't respond after an update | Hard-refresh the browser tab (Cmd+Shift+R / Ctrl+Shift+R). An open tab keeps the old page code after the server restarts. |
| `agent: mock` shows although Claude is installed | The `claude` CLI isn't on the app's PATH. Set `VALOR_CLAUDE_BIN=/full/path/to/claude`. |
| Agent features are slow | Each Claude call takes about 15–20 s and costs roughly $0.08–0.11. Use `VALOR_AGENT_MODE=mock` for demos. |
| "Inputs changed since this run" | Press **Re-run** on the Valuation step. |
| Can't submit | The Approval checklist names what's missing. |
| Can't approve | Switch **Acting as** to a reviewer who didn't submit the case. |
| Start over with fresh demo data | Stop the app, move `var/valor.db` somewhere safe, then run `scripts/seed_demo_cases.py`. |
| Experiment without touching your cases | `cp var/valor.db /tmp/play.db` then `VALOR_DB=/tmp/play.db VALOR_PORT=8071 .venv/bin/python -m valor` |

---

## 9. Going beyond the mock

Valor is built so that real components drop in without code changes elsewhere:
- **Data:** the Snowflake data tool and table names.
- **Market data:** Bloomberg-fed tables.
- **The master Excel workbook:** translated to Python and verified method by method.
- **Credit policy limits, memo templates, Google Docs export and users/roles.**

The step-by-step table is in the [README](../README.md#swapping-in-real-data-models-and-templates), and
`templates/reports/README.md` explains memo templates.
