# Valor

A prototype of an agentic enterprise valuation reviewer for a commercial bank's second line.
Valor gives an independent view of the enterprise value (performing deals) or the bank's recovery
(troubled deals) behind a commercial loan. It challenges the first line's valuation assumption by
assumption and ends in a formal opinion. Every input change, agent recommendation, reviewer
challenge and approval is on the record.

**All data, names and numbers are mock.** The bank is "Generic Commercial Bank".

- New here? Read the **[user guide](docs/USER_GUIDE.md)**: setup, a full walkthrough, and how to swap in real data.
- Working on the code with Claude Code? See **[CLAUDE.md](CLAUDE.md)**.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python scripts/seed_demo_cases.py     # optional: three demo cases in different states
.venv/bin/python -m valor                       # http://127.0.0.1:8050
.venv/bin/python -m pytest                      # 28 tests
```

Use **Acting as** (top right) to switch between analysts (makers) and reviewers (checkers).
Run with `VALOR_AGENT_MODE=mock` to use deterministic rules instead of Claude (free, instant, offline).

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `VALOR_PORT` | `8050` | Port for the web app |
| `VALOR_AGENT_MODE` | from `config/settings.yaml` (`auto`) | `auto` (Claude if the CLI is on PATH, else rules), `claude`, or `mock` |
| `VALOR_DB` | `var/valor.db` | SQLite file; point at a copy to experiment without touching your cases |
| `VALOR_CLAUDE_BIN` | `claude` | Path to the Claude Code CLI |
| `VALOR_DEBUG` | off | `1` runs Dash in debug mode |

## How it fits together

```
Dash UI (valor/ui)  ──►  services (valor/service.py)  ──►  SQLite (cases, inputs, runs, challenges, audit log)
                              │
          ┌───────────────────┼─────────────────────┬──────────────────────┐
   DataSource            Valuation engine       Agent layer             Reports / share
 (valor/data)          (valor/engine)          (valor/agent)           (valor/report, share.py)
 mock CSV ⇄ Snowflake   deterministic Python    claude -p, headless     findings → any template
                        one module per method   judgment + language     Gmail compose link
```

- **Numbers come only from the engine.** Claude is used for judgment and language: Excel
  translation, valuation commentary, input-adjustment recommendations, opinion drafts, memo
  narrative and email drafts. Its proposals are input values that a person accepts, edits or
  rejects; the engine then recomputes. `valor/agent/numguard.py` flags any figure in model-written
  prose that does not appear in the engine output.
- **Workflows are config.** `config/workflows/performing.yaml` and `troubled.yaml` define the inputs
  (with their Snowflake source), methods, weights, steps and memo sections. A new workflow is a new
  YAML file; no code change.
- **Policy is config.** Add-back acceptance defaults, the add-back cap, LTV and coverage limits and the
  traffic-light bands are under `policy` in `config/settings.yaml`. All are placeholders.

## The review flow

Each case moves through eight steps, with the audit trail alongside:

1. **Scope**: the review trigger and due date, the exposure, the first line's valuation package
   (EBITDA, multiple, WACC, growth, recovery), and the pulled data. Each table is shown in a tab, with a CSV
   download per table and an Excel workbook of everything.
2. **Earnings**: the EBITDA bridge. Management presents adjusted EBITDA with add-backs; the second line
   accepts each in whole or part (defaults: synergies 0%, pro forma 50%, one-time/QoE-verified 100%).
   Normalized EBITDA drives every multiple. Accepted add-backs above 20% of reported EBITDA are flagged.
3. **Assumptions**: your changes pinned at the top, then a workbench of every input by group. Each input
   shows its source, and five-year projections are shown as a Y1–Y5 grid. Every change needs a rationale.
4. **Valuation**: headline numbers; how the value is built (football field, method cards that expand into
   their workings); what it means for the loan (downside case and policy tests with headroom for
   performing deals; PV of recovery, specific reserve and claims stack for troubled ones); agent commentary
   (written automatically after each run) beside the review checks; and a **What-if** sandbox.
5. **Challenge**: first line vs second line, assumption by assumption, with a traffic light per row;
   reviewer challenges to answer; agent recommendations to accept, edit or reject.
6. **Opinion**: Concur / Concur with exceptions / Do not concur, with rationale, conditions, top risks and
   questions for the first line. Rules suggest a verdict (traffic light on variance: green ≤ 5%,
   amber ≤ 15%, red > 15%; policy tests; high-severity checks). The agent can draft it; the analyst decides.
7. **Approval**: maker-checker. Submitting needs a current valuation, decided recommendations, answered
   challenges and an opinion on the latest run. A different person with the reviewer role approves (which
   locks the case) or sends it back.
8. **Deliver**: the memo (opinion first) in any template, as HTML (print to PDF), .docx and Markdown, plus
   a prefilled Gmail compose link. Valor never sends email.

**Reviewer challenges.** While a case is in review its inputs are frozen. The reviewer uses What-if to
override any assumption and see the effect on value, LTV, coverage, reserve, the traffic light and the
suggested verdict; nothing is saved. If it matters, the reviewer sends the case back with those values as
challenges. The analyst accepts each one (the value is applied as an audited adjustment) or declines it with a
written response, then re-runs, re-confirms the opinion and resubmits.

## Auditability

`valor/store.py` keeps an append-only audit log: SQLite triggers refuse UPDATE and DELETE, and each entry is
hash-chained to the one before it, so an edit made outside the app is detectable (the Audit trail page shows
whether the chain verifies). It records:

- input changes: field, source value, old and new value, user, time, rationale;
- agent recommendations and their outcomes, reviewer challenges and their resolution;
- every agent call: mode, duration and cost. The prompt and output are saved in `var/agent_runs/`;
- workflow events: data pulls and exports, valuation runs (with an inputs hash), opinions, submit, send back,
  approve, lock, reports (with a findings hash), emails opened.

## Headless Claude calls

`valor/agent/runner.py` shells out to the Claude Code CLI on the laptop. It never calls Bedrock directly;
the CLI is already configured for Bedrock:

```
claude -p "<prompt>" --output-format json --json-schema '<schema>' --append-system-prompt "<prompts/system.md>"
       --tools "" --setting-sources "" --no-session-persistence --max-turns 3 [--model <id>]
```

Each call runs in an empty temp directory with no tools and no project settings, and returns JSON matching
the schema. Prompts are in `prompts/*.md`, one per task: recommend, explain, opinion, narrative, email,
translate_excel. In testing, a call took 15–20 s and cost $0.08–0.11 with the CLI's default model. In
`auto` mode a failed call falls back to the deterministic rules and is logged.

## Excel → Python translation

The mock master workbook (`workbook/master_valuation.xlsx`, built by `scripts/build_mock_workbook.py`) has
DCF, Comps, Precedents, Liquidation and Summary tabs as live formulas. `workbook/mapping.yaml` maps each
engine input and output to a cell. The `formulas` package recalculates the workbook without Excel.

```bash
python -m valor.excel extract                                   # formulas + values → translations/workbook_spec.json
python -m valor.excel propose --method dcf                      # Claude proposes translations/dcf/v1/proposed.py
python -m valor.excel verify  --method dcf --version 1          # run on the workbook's inputs; compare outputs
python -m valor.excel approve --method dcf --version 1 --reviewer m.reyes [--activate]
python -m valor.excel status
```

Approval requires a passing verification, a reviewer role and an unchanged file hash. The approved module is
copied to `valor/engine/translated/`, recorded in `translations/registry.json` and, with `--activate`, wired
into `config/engine.yaml`. `tests/test_workbook_parity.py` checks the active engine against the workbook on every
test run; the Engine page does the same on demand.

## Swapping in real data, models and templates

| Placeholder | Where | What to do |
|---|---|---|
| Snowflake data tool | `valor/data/snowflake_adapter.py` | Implement `_query` with the internal tool; set `data.source: snowflake` |
| Real table names | `config/data_sources.yaml` | Replace the physical names; keep the logical column names (alias in SQL) |
| Market data | `data/mock/mkt_*.csv` | Point the `mkt_*` entries at the Bloomberg-fed tables |
| First-line packages, add-backs | `data/mock/first_line_valuation.csv`, `ebitda_adjustments.csv` | Map to where deal teams record their valuation and adjusted EBITDA |
| Master workbook | `workbook/master_valuation.xlsx`, `workbook/mapping.yaml` | Drop in the real workbook, map its cells, run the translation workflow per method |
| Valuation methods | `config/engine.yaml` | Point a method at another module with the same `build_inputs` / `run` contract |
| Input sources and defaults | `config/workflows/*.yaml` | Each input's `source` string; the syntax is at the top of performing.yaml |
| Credit policy | `config/settings.yaml` (`policy`, `review`), `valor/engine/checks.py` | Replace with the bank's limits and thresholds |
| Report templates | `templates/reports/` | See `templates/reports/README.md` |
| Google Docs / Gmail draft | `apps_script/Code.gs`, `google.apps_script_url` | Deploy as a web app; the Deliver step enables its buttons |
| Users and roles | `config/users.yaml` | Replace with SSO / entitlements; "Acting as" is a stand-in |

## Design language

One set of rules across every page (helpers in `valor/ui/components.py`):

- **Page / step header** (`step_head`): serif title, up to three chips, one primary action on the right. No
  explanatory prose; explanations live in ⓘ tooltips (`tip`).
- **Section** (`section`): every content block is a white sheet with a serif title, an optional ⓘ and actions
  on the right.
- **Metric tiles** (`kpis`, `.card` with `.big`): numbers lead, words follow.
- **Expanding cards** (`expandable`): any card with detail behind it grows into a centred sheet (home cases,
  method workings, loan metrics, engine methods). Click to open, Esc to close.
- **Gold-topped cards** (`.gate`): reserved for decisions (opinion, submit, approve).
- **Colour carries meaning only**: green / amber / red for status and variance, brass for changes made by a
  person, navy for actions.
- **Next →** at the bottom of each step.

The palette is navy (`#004977`) on cool paper with one brass accent, Fraunces headings and Hanken Grotesk body
text (`valor/ui/assets/valor.css`).

## Repository map

```
config/            settings (agent, policy, review), data-source table map, users, engine registry, workflows/*.yaml
data/mock/         placeholder Snowflake tables (scripts/seed_mock_data.py)
workbook/          mock master workbook + cell mapping (scripts/build_mock_workbook.py)
prompts/           system prompt and one prompt per agent task
templates/reports/ memo templates (Jinja2 + Markdown)
docs/USER_GUIDE.md setup and usage guide
valor/data/        DataSource interface, mock, Snowflake adapter stub, input resolvers
valor/engine/      dcf, comps, precedents, liquidation, distressed, waterfall, review (earnings, downside, reserve,
                   policy, first-line comparison), checks
valor/agent/       claude -p runner, tasks, numguard
valor/excel/       workbook recalculation, parity, translation CLI
valor/report/      findings builder and renderers (HTML, .docx, Markdown)
valor/service.py   every state change (cases, inputs, runs, recommendations, opinion, challenges, maker-checker)
valor/ui/          Dash app: app.py (shell, callbacks, file routes), pages/, components.py, charts.py, assets/
apps_script/       Google Workspace hook (placeholder)
scripts/           seed mock data, build the workbook, seed demo cases
tests/             engine, workbook parity, workflow / maker-checker / challenges / audit
var/               runtime data (SQLite, reports, agent run logs); gitignored
```
