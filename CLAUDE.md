# CLAUDE.md

Guidance for Claude Code when working in this repository. User-facing docs: `README.md` (overview) and
`docs/USER_GUIDE.md` (setup and walkthrough).

## What this is

Valor is a prototype second-line enterprise valuation reviewer for a commercial bank (Python 3.12, Dash 3.1,
SQLite). All data is mock; treat the bank as generic and never add real institution names or confidential data.

## Commands

```bash
.venv/bin/python -m pytest -q                                   # 28 tests; must stay green
.venv/bin/python -m valor                                       # app on :8050 (VALOR_PORT to change)
VALOR_AGENT_MODE=mock .venv/bin/python -m valor                 # no Claude calls
.venv/bin/python scripts/seed_demo_cases.py                     # demo cases into var/valor.db
.venv/bin/python scripts/seed_mock_data.py                      # regenerate data/mock/*.csv
.venv/bin/python scripts/build_mock_workbook.py                 # regenerate the workbook + mapping
.venv/bin/python -m valor.excel status                          # engine vs workbook parity
```

- The server does not hot-reload. After changing Python, CSS or JS, restart it, and tell the user to hard-refresh
  (Cmd+Shift+R): an open tab keeps the old JavaScript.
- To try changes without touching the user's cases, copy `var/valor.db` to a scratch path and run with
  `VALOR_DB=<copy> VALOR_PORT=<other port>`. Never edit, delete or reseed `var/valor.db` without asking; it
  holds the user's working cases.
- Tests run with `VALOR_AGENT_MODE=mock` and a temp DB (`tests/conftest.py`); they never call Claude.

## Invariants (do not break)

1. **Numbers come only from the deterministic engine** (`valor/engine/`). Claude may propose *input* values
   (a person accepts them) and write prose. Never let model output become a valuation figure. Model prose
   goes through `valor/agent/numguard.py`.
2. **Every state change goes through `valor/service.py`** and writes the audit log (`store.audit`). The UI never
   writes to the database directly.
3. **The audit log is append-only and hash-chained** (`valor/store.py`). Don't add UPDATE/DELETE paths or
   change the hash fields.
4. **Every input change needs a rationale.** Adjustments go through `service.adjust_input`, including those
   applied from agent recommendations and reviewer challenges.
5. **Maker-checker:** the submitter cannot approve (`review.allow_self_approval: false`). Submitted cases are
   frozen (`ensure_editable`). Approved cases are locked.
6. **The engine must match the workbook.** `tests/test_workbook_parity.py` must pass. A method module exposes
   `VERSION`, `build_inputs(values, claims)` and `run(inputs) -> MethodResult`.
7. **Claude is reached only via `claude -p`** in `valor/agent/runner.py` (empty cwd, no tools, JSON schema).
   Never call Bedrock or any API directly. Every task needs a deterministic `mock` fallback.
8. **Never send email.** Sharing is a Gmail compose link or an Apps Script *draft*.

## Where things go

| Change | Where |
|---|---|
| New input or default | `config/workflows/<workflow>.yaml` (`source` syntax documented at the top of performing.yaml); resolvers in `valor/data/resolvers.py` |
| New workflow | A new YAML in `config/workflows/` |
| Policy limits, thresholds | `config/settings.yaml` (`policy`, `review`); rule checks in `valor/engine/checks.py` |
| New valuation method | A module in `valor/engine/`, registered in `config/engine.yaml`, mapped in `workbook/mapping.yaml`, with parity coverage |
| Review analytics (earnings bridge, downside, reserve, policy tests, first-line comparison, suggested verdict) | `valor/engine/review.py` |
| New agent task | Function in `valor/agent/tasks.py` (schema + mock), prompt in `prompts/<task>.md` |
| New data table | `config/data_sources.yaml`, `data/mock/<name>.csv` (via `scripts/seed_mock_data.py`), accessor on `DataSource` |
| Memo content | `valor/report/findings.py` (data) and `templates/reports/*.md.j2` (layout) |
| UI | `valor/ui/pages/case.py` (case steps), `cases.py` (home, new case), `engine.py`; callbacks in `valor/ui/app.py` |

## UI conventions

Follow the design language in `README.md` ("Design language") and reuse `valor/ui/components.py`:

- `step_head` for each step; `section` for every content block; `kpis` / `.card` tiles for numbers.
- `expandable` for any card with detail behind it. Put the returned sheets outside animated panels (they are
  `position: fixed`).
- `tip` (ⓘ) for explanations, sources, paths and hashes. Avoid explanatory paragraphs on the page.
- `.gate` (gold top) only for decisions: opinion, submit, approve.
- Colour carries meaning only. Navy (`--primary-*`) is for actions, brass for human changes, and
  green/amber/red for status.
- Buttons that trigger actions use the pattern id `{"type": "act", "name": ...}`, handled by `dispatch` in
  `app.py`. Form fields read by actions use `{"type": "field", "name": ...}`.
- Client-side behaviour (filter chips, expanding sheets, anchor scroll) lives in `valor/ui/assets/interactions.js`.
- After a UI change, render every page at least once, e.g.
  `from valor.ui.app import route; route('/case/VAL-2026-0001/valuation', 0, 'a.chen')`, and check for
  "Error rendering". Screenshot the changed pages with the gstack browse tool.

## Style

- Prose in the UI and docs is plain and short: no marketing tone, no em-dash asides.
- Money is USD millions (`valor/fmt.py`: `money`, `pct`, `fmt`). Percentages are stored as decimals.
- Keep placeholders clearly marked (`PLACEHOLDER` / `TODO(bank)`), so real data, models and templates can be dropped in.
