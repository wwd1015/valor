"""Small presentational helpers (Cyber Credit Officer style)."""

from __future__ import annotations

from dash import html

from valor.config import user
from valor.fmt import fmt

STATUS_BADGE = {"draft": ("Draft", ""), "submitted": ("In review", "accent"), "returned": ("Sent back", "bad"),
                "approved": ("Approved · locked", "good")}


def badge(text, tone: str = "") -> html.Span:
    return html.Span(text, className=f"badge {tone}".strip())


def status_badge(status: str) -> html.Span:
    label, tone = STATUS_BADGE.get(status, (status, ""))
    return badge(label, tone)


def kpis(items: list[tuple]) -> html.Div:
    """items: (label, value, hint, tone) with hint/tone optional."""
    out = []
    for it in items:
        label, value = it[0], it[1]
        hint = it[2] if len(it) > 2 else None
        tone = it[3] if len(it) > 3 else ""
        out.append(html.Div([html.Div(label, className="kpi-label"),
                             html.Div(value, className=f"kpi-value {'accent' if tone == 'accent' else ''}"),
                             html.Div(hint, className=f"kpi-hint {tone}") if hint else None], className="kpi"))
    return html.Div(out, className="kpis")


def table(columns: list[tuple], rows: list[dict], row_class=None) -> html.Div:
    """columns: (key, label, kind) with kind in {"", "num"}."""
    head = html.Tr([html.Th(lab, className="r" if kind == "num" else "") for _, lab, kind in columns])
    body = []
    for r in rows:
        cls = row_class(r) if row_class else ""
        body.append(html.Tr([html.Td(r.get(k), className=("num r" if kind == "num" else "")) for k, _, kind in columns],
                            className=cls))
    return html.Div(html.Table([html.Thead(head), html.Tbody(body)], className="tbl"), className="tbl-wrap")


COL_LABEL = {"d_and_a": "D&A", "change_nwc": "Change in NWC", "ev_ebitda": "EV / EBITDA", "ev_revenue": "EV / revenue",
             "amount_musd": "Amount", "ev_musd": "EV", "adj_id": "ID", "claim_id": "ID", "musd": ""}
PCT_HINTS = ("rate", "growth", "margin", "share", "recovery_", "premium", "debt_to_cap", "value")


def _col_kind(col: str, series) -> str:
    if "year" in col or col.endswith("_date") or col in ("priority",):
        return "int"
    if series.dtype.kind in "fi":
        vals = series.dropna()
        if any(h in col for h in PCT_HINTS) and len(vals) and vals.abs().max() <= 1.5 and col not in ("value",):
            return "pct"
        if col == "value" and len(vals) and vals.abs().max() <= 1.5:
            return "pct"
        if col in ("ev_ebitda", "ev_revenue", "multiple_used"):
            return "x"
        if col == "unlevered_beta":
            return "num"
        return "money"
    return "text"


def _fmt_cell(v, kind):
    if v is None or (isinstance(v, float) and v != v):
        return "—"
    if kind == "int":
        try:
            return str(int(v))
        except (TypeError, ValueError):
            return str(v)
    if kind == "pct":
        return f"{v * 100:.1f}%"
    if kind == "x":
        return f"{v:.1f}x"
    if kind == "num":
        return f"{v:.2f}"
    if kind == "money":
        return f"{v:,.1f}"
    if isinstance(v, bool):
        return "Yes" if v else "No"
    return str(v)


def df_table(df, cols: list[str] | None = None, max_rows: int = 40, units: dict | None = None) -> html.Div:
    if df is None or df.empty:
        return html.P("No rows.", className="muted small")
    cols = cols or list(df.columns)
    kinds = {c: _col_kind(c, df[c]) for c in cols}
    rows = [{c: _fmt_cell(r[c], kinds[c]) for c in cols} for _, r in df.head(max_rows).iterrows()]
    label = lambda c: COL_LABEL.get(c, c.replace("_musd", "").replace("_", " ").capitalize())  # noqa: E731
    return table([(c, label(c), "num" if kinds[c] in ("money", "pct", "x", "num") else "") for c in cols], rows)


def who(uid: str | None) -> str:
    if not uid:
        return ""
    if uid.startswith("agent:"):
        return f"Agent ({uid.split(':', 1)[1]})"
    return user(uid)["name"]


def notice(children, tone: str = "") -> html.Div:
    return html.Div(children, className=f"notice {tone}".strip())


def agent_voice(text: str, meta: str | None = None) -> html.Div:
    return html.Div([html.Div(text, className="agent-voice"), html.Div(meta, className="agent-meta") if meta else None])


# ── cards-first components (design brief) ────────────────────────────

VERDICT_LABEL = {"concur": "Concur", "concur_with_exceptions": "Concur with exceptions", "do_not_concur": "Do not concur"}
RAG_LABEL = {"green": "Green", "amber": "Amber", "red": "Red", "grey": "No run"}


def tip(text: str) -> html.Span:
    """An ⓘ with a hover/focus tooltip for provenance, paths, hashes and method notes."""
    return html.Span("i", className="tip", tabIndex="0", role="note", **{"data-tip": text, "aria-label": text})


def rag_chip(status: str | None, text: str | None = None) -> html.Span:
    s = status or "grey"
    return html.Span(text or RAG_LABEL[s], className=f"rag {s}")


def verdict_chip(verdict: str | None) -> html.Span:
    if not verdict:
        return html.Span("Opinion pending", className="verdict pending")
    return html.Span(VERDICT_LABEL[verdict], className=f"verdict {verdict}")


def step_head(title: str, chips: list | None = None, action=None) -> html.Div:
    return html.Div([html.Div([html.H2(title, className="step-title"), *(chips or [])], className="chips"),
                     html.Div(action) if action else None], className="step-head")


def mini(label: str, value, sub=None, tone: str = "") -> html.Div:
    return html.Div([html.Div(label, className="mini-label"),
                     html.Div([value, html.Small(sub, className=tone) if sub else None], className="mini-value")], className="mini")


def empty_state(title: str, action=None) -> html.Div:
    return html.Div(html.Div([html.Div(title, className="card-title"), html.Div(action, style={"marginTop": "10px"}) if action else None]),
                    className="card-empty")


# ── expanding cards: a card grows into a centred sheet (assets/interactions.js) ──

def expandable(sheet_id: str, title: str, eyebrow: str, stats: list[tuple], body: list, card_children: list,
               card_class: str = "card", hint: str = "Details", attrs: dict | None = None, actions: list | None = None) -> tuple:
    """A card that grows into a centred sheet (assets/interactions.js handles [data-expand]). Returns (card, sheet)."""
    head_stats = [html.Div([html.Div(k, className="mini-label"), html.Div(v, className="mini-value")], className="mini") for k, v in stats]
    sheet = html.Div(html.Div([
        html.Div([html.Div([html.Div(eyebrow, className="eyebrow"), html.H2(title, className="step-title"),
                            html.Div(actions, className="btn-row", style={"marginTop": "10px"}) if actions else None]),
                  html.Div([*head_stats, html.Button("×", className="sheet-close", title="Close (Esc)", **{"data-close": "1", "aria-label": "Close"})],
                           className="band-stats", style={"alignItems": "flex-start"})], className="sheet-head"),
        html.Div(body, className="sheet-body"),
    ], className="sheet", role="dialog", **{"aria-modal": "true", "aria-label": f"{title}: {eyebrow.lower()}"}), id=sheet_id, className="sheet-overlay")
    card = html.Div([*card_children, html.Div(f"{hint} ↗", className="expand-hint")], className=f"{card_class} expandable",
                    role="button", tabIndex="0", **{"data-expand": sheet_id, "aria-label": f"{title}: {hint.lower()}", **(attrs or {})})
    return card, sheet


def kv_table(rows: list[tuple]) -> html.Div:
    return table([("k", "", ""), ("v", "", "num")], [{"k": k, "v": v} for k, v in rows])


def section(title, children, right=None, tip_text=None, id=None) -> html.Div:
    """The standard content block: a white sheet with a serif title, an optional ⓘ and actions on the right."""
    head = html.Div([html.Div([html.H3(title, className="panel-title"), tip(tip_text) if tip_text else None], className="chips"),
                     right], className="step-head", style={"marginBottom": "12px"})
    kw = {"id": id} if id else {}
    return html.Div([head, *(children if isinstance(children, list) else [children])], className="panel", style={"paddingTop": "16px"}, **kw)


def checklist(items: list[tuple]) -> html.Div:
    """Pre-conditions as a vertical list of ✓ / missing rows."""
    return html.Div([html.Div([html.Span("✓" if ok else "!", className=f"ck {'ok' if ok else 'no'}"), html.Span(label)], className="ck-row")
                     for label, ok in items], className="ck-list")
