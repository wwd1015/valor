# Report templates

A template is a Jinja2 + Markdown file named `*.md.j2`. Put house templates in this folder, or
upload one from a case's Report step (it lands in `uploaded/`). Every template renders the same
structured findings, so the numbers are identical across formats.

The first line may declare metadata:

```
{# name: Credit memo | description: Full memo for the credit file | layout: memo #}
```

`layout: slides` splits the document into slides at each `---` line (HTML deck, page breaks in .docx).

Templates render in a sandboxed Jinja environment with undefined variables treated as errors,
so a bad upload is rejected at upload time rather than producing a half-filled report.

## Available variables

| Variable | Contents |
|---|---|
| `institution`, `units`, `generated_at`, `generated_by`, `status`, `locked` | report header |
| `deal` | `case_id, borrower, sector, facility, lien, risk_status, commitment, outstanding, relationship_manager, internal_rating, first_line_method` |
| `workflow` | `name, tagline, description, methods` |
| `results` | list of methods: `label, measure, low, mid, high, weight, version` |
| `conclusion` | `measure_label, low, mid, high, first_line_value, vs_first_line, variance_flag, bank_exposure, statement`; performing adds `ltv, coverage, debt_ahead`; troubled adds `recovery_pct, recovery_pct_low, recovery_pct_high` |
| `key_inputs` | `group, label, value, source_value, source, adjusted` |
| `adjustments` | `label, from, to, rationale, by, when, via_agent` |
| `recommendations` | `title, severity, status, field, current, proposed, final, decided_by, note, source` |
| `approvals` | `action, by, role, when, comment` |
| `waterfall` | troubled only: `scenario, priority, claim, claim_amount, recovered, recovery_pct, bank` |
| `dcf` | performing only: `wacc, cost_of_equity, levered_beta, terminal_share, implied_exit_multiple, projection[]` |
| `narrative` | `executive_summary, methodology_commentary, key_judgements, conclusion` (agent-drafted, or deterministic) |
| `narrative_source`, `narrative_unverified` | who drafted the narrative; figures not found in engine output |
| `run`, `audit`, `findings_hash` | provenance: run id, inputs hash, engine versions, audit chain status |

Filter: `| cell` makes a value safe inside a Markdown table cell.

## Swapping in the bank's real templates

1. Recreate the bank memo's section order in a `.md.j2` file, using the variables above.
2. If the bank needs a `.docx` with exact styling, render the Markdown here and post-process,
   or replace `to_docx` in `valor/report/render.py` with a docxtpl-based renderer over a styled
   Word template: the findings dict stays the same.
