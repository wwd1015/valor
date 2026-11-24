"""The case workspace: a compact band, a stepper rail, and one step at a time.

Flow (an independent second-line review):
  Scope → Earnings → Assumptions → Valuation → Challenge → Opinion → Approval → Deliver  (+ Audit)
"""

from __future__ import annotations

import json

from dash import dcc, html

from valor import service, store
from valor.agent import runner
from valor.config import settings, user
from valor.engine.review import VERDICTS
from valor.fmt import fmt, money, pct
from valor.integrations import google
from valor.report import render as report_render
from valor.ui import charts
from valor.ui.components import (section as _section, checklist, expandable as _expandable, kv_table as _kv_table, agent_voice, badge, df_table, empty_state, kpis, mini, rag_chip, status_badge, step_head,
                                 table, tip, verdict_chip, who)
from valor.workflow import template

STEPS = [("scope", "Scope"), ("earnings", "Earnings"), ("assumptions", "Assumptions"), ("valuation", "Valuation"),
         ("challenge", "Challenge"), ("opinion", "Opinion"), ("approval", "Approval"), ("deliver", "Deliver")]
ALIASES = {"intake": "scope", "data": "scope", "inputs": "assumptions", "recommendations": "challenge",
           "review": "approval", "report": "deliver", "share": "deliver"}


def act(name: str) -> dict:
    return {"type": "act", "name": name}


def field(name: str) -> dict:
    return {"type": "field", "name": name}


def _editable(case) -> bool:
    return case["status"] in service.EDITABLE and not case["locked"]


def _ts(s: str | None) -> str:
    return (s or "")[:16].replace("T", " ")


# ── shell ────────────────────────────────────────────────────────────

def _context(case: dict) -> dict:
    cid = case["id"]
    run = service.latest_run(cid)
    recs = service.recommendations(cid)
    op = case["opinion"]
    return {"run": run, "current": service.run_is_current(cid) if run else False,
            "n_adj": len(service.adjustments(cid)) if case["data_pulled_at"] else 0,
            "open_recs": sum(1 for r in recs if r["status"] == "open"), "n_recs": len(recs),
            "opinion_current": bool(op and run and op["run_id"] == run["id"]),
            "open_challenges": sum(1 for x in service.challenges(cid) if x["status"] == "open"),
            "n_reports": len(store.rows("SELECT id FROM reports WHERE case_id = ?", (cid,)))}


def _rail_state(case: dict, step: str, ctx: dict) -> tuple[str, str]:
    pulled = bool(case["data_pulled_at"])
    if step == "scope":
        return ("", "done") if pulled else ("start", "todo")
    if step == "earnings":
        return ("", "done") if pulled else ("", "")
    if step == "assumptions":
        return (f"{ctx['n_adj']} adj." if ctx["n_adj"] else "", "done") if pulled else ("", "")
    if step == "valuation":
        if not ctx["run"]:
            return ("run", "todo") if pulled else ("", "")
        return ("", "done") if ctx["current"] else ("re-run", "todo")
    if step == "challenge":
        if ctx["open_challenges"]:
            return (f"{ctx['open_challenges']} challenge(s)", "todo")
        if ctx["open_recs"]:
            return (f"{ctx['open_recs']} open", "todo")
        return ("", "done") if ctx["n_recs"] else ("", "")
    if step == "opinion":
        if ctx["opinion_current"]:
            return ("", "done")
        return ("to do", "todo") if ctx["run"] else ("", "")
    if step == "approval":
        return {"draft": ("", ""), "submitted": ("in review", "todo"), "returned": ("sent back", "todo"),
                "approved": ("", "done")}[case["status"]]
    if step == "deliver":
        return (str(ctx["n_reports"]), "done") if ctx["n_reports"] else ("", "")
    return "", ""


def render(case_id: str, step: str, uid: str) -> html.Div:
    try:
        case = service.get_case(case_id)
    except service.ReviewError as e:
        return html.Div(str(e), className="notice bad")
    step = ALIASES.get(step, step)
    t = template(case["workflow"])
    ctx = _context(case)

    rail = []
    for i, (sid, label) in enumerate(STEPS, start=1):
        state, tone = _rail_state(case, sid, ctx)
        cls = " ".join(x for x in ("active" if sid == step else "", tone) if x)
        rail.append(dcc.Link([html.Span("✓" if tone == "done" else str(i), className="step-dot"), html.Span(label),
                              html.Span(state, className=f"rail-state {tone}")], href=f"/case/{case_id}/{sid}", className=cls))
    rail.append(html.Div(className="rail-sep"))
    rail.append(dcc.Link([html.Span("§", className="step-dot"), html.Span("Audit trail"),
                          html.Span(str(len(store.audit_trail(case_id))), className="rail-state")],
                         href=f"/case/{case_id}/audit", className="active" if step == "audit" else ""))

    body = {"scope": _scope, "earnings": _earnings, "assumptions": _assumptions, "valuation": _valuation,
            "challenge": _challenge, "opinion": _opinion, "approval": _approval, "deliver": _deliver,
            "audit": _audit}.get(step, _scope)(case, t, uid, ctx)
    return html.Div([_band(case, t, ctx), _statusline(case, uid, ctx),
                     html.Div([html.Nav(rail, className="rail"), html.Div(body)], className="workspace")])


def _band(case, t, ctx) -> html.Div:
    d = case["deal"]
    run = ctx["run"]
    c = run["results"]["conclusion"] if run else None
    facts = html.Dl([html.Dt("Sector"), html.Dd(case["sector"]), html.Dt("Facility"), html.Dd(f"{d.get('facility_name')} · {d.get('lien_position')}"),
                     html.Dt("Risk"), html.Dd(f"{d.get('risk_status')} · rating {d.get('internal_rating')}"),
                     html.Dt("RM"), html.Dd(d.get("relationship_manager")), html.Dt("Analyst"), html.Dd(who(case["created_by"]))],
                    className="facts")
    stats = [mini("Exposure", money(d.get("commitment_musd"))), mini("1st line", money(d.get("first_line_value_musd")))]
    if c:
        vs = c.get("vs_first_line")
        tone = {"red": "kpi-hint bad", "amber": "kpi-hint", "green": "kpi-hint good"}.get(c.get("rag"), "")
        stats.append(mini("2nd line", money(c["mid"]), pct(vs, signed=True) if vs is not None else None, tone))
        rv = run["results"].get("reserve")
        if rv:
            stats.append(mini("Reserve", money(rv["reserve_mid"]), pct(rv["reserve_pct_mid"])))
    op = case["opinion"]
    return html.Div([
        html.Div([
            html.Div([status_badge(case["status"]), badge(t["name"], "accent" if t["id"] == "troubled" else ""),
                      rag_chip(c.get("rag")) if c else None, verdict_chip(op["verdict"]) if op else None], className="band-badges"),
            html.H1(case["borrower_name"], className="band-name"),
            html.Div([html.Span(f"{case['id']} · {case['deal_id']} · {d.get('request_type', '')}"),
                      html.Span(f"Due {d.get('review_due')}") if d.get("review_due") else None,
                      html.Details([html.Summary("Deal facts ▾"), facts])], className="band-sub"),
        ]),
        html.Div(stats, className="band-stats"),
    ], className="band")


def _statusline(case, uid=None, ctx=None):
    cid = case["id"]
    if case["locked"]:
        return html.Div([badge("Locked", "good"), f"Approved by {who(case['approved_by'])}. Read-only; What-if on the Valuation step still works."],
                        className="statusline locked")
    if case["status"] == "submitted":
        me = user(uid) if uid else {}
        reviewer = me.get("role") in ("reviewer", "admin") and uid != case["submitted_by"]
        return html.Div([f"In review · submitted by {who(case['submitted_by'])} · inputs frozen",
                         dcc.Link("Challenge an assumption →", href=f"/case/{cid}/valuation#whatif", style={"marginLeft": "auto"}) if reviewer else None],
                        className="statusline review")
    if case["status"] == "returned":
        last = [r for r in service.reviews(cid) if r["action"] == "send_back"][-1:]
        n = (ctx or {}).get("open_challenges", 0)
        return html.Div([f"Sent back by {who(last[0]['actor'])}: “{last[0]['comment']}”" if last else "Sent back",
                         dcc.Link(f"Answer {n} challenge(s) →", href=f"/case/{cid}/challenge", style={"marginLeft": "auto", "whiteSpace": "nowrap"})
                         if n else None], className="statusline returned")
    return None


def _next(label: str, href: str):
    return dcc.Link(label + " →", href=href, className="btn")


# ── 1 scope ──────────────────────────────────────────────────────────

TABLES = {"financials": ("Financials", "FIN_STATEMENT_ANNUAL"), "projections": ("Projections", "FIN_PROJECTION"),
          "ebitda_adjustments": ("EBITDA add-backs", "EBITDA_ADJUSTMENTS"), "capital_structure": ("Claims stack", "CAPITAL_STRUCTURE"),
          "assets": ("Assets", "BALANCE_SHEET_ASSETS"), "trading_comps": ("Trading comps", "MKT_TRADING_COMPS"),
          "precedent_transactions": ("Precedents", "MKT_PRECEDENT_TRANSACTIONS"),
          "distressed_transactions": ("Distressed deals", "MKT_PRECEDENT_TRANSACTIONS"),
          "rates": ("Market rates", "MKT_RATES"), "recovery_rates": ("Recovery rates", "MKT_RECOVERY_RATES")}


def _scope(case, t, uid, ctx):
    d = case["deal"]
    pulled = bool(case["data_pulled_at"])
    fl = case["extras"].get("first_line") or {}
    action = None
    if _editable(case):
        action = html.Button("Pull data" if not pulled else "Re-pull", id=act("pull"), className="btn primary" if not pulled else "btn small")
    cards = [
        html.Div([html.Div("Trigger", className="mini-label"), html.Div(d.get("request_type"), className="card-title"),
                  html.Div(f"Due {d.get('review_due')} · {d.get('risk_status')}", className="card-metric")], className="card"),
        html.Div([html.Div("Exposure", className="mini-label"), html.Div(money(d.get("commitment_musd")), className="big"),
                  html.Div(f"{money(d.get('outstanding_musd'))} drawn · {d.get('lien_position')}", className="card-metric")], className="card"),
        html.Div([html.Div("First-line value", className="mini-label"), html.Div(money(d.get("first_line_value_musd")), className="big"),
                  html.Div(d.get("first_line_method"), className="card-metric")], className="card accent"),
    ]
    if fl:
        rows = [("EBITDA used", fmt(fl.get("ebitda_used"), "musd")), ("Multiple", fmt(fl.get("multiple_used"), "x"))]
        if fl.get("wacc") is not None:
            rows += [("WACC", fmt(fl["wacc"], "pct")), ("Terminal g", fmt(fl.get("terminal_growth"), "pct")),
                     ("Growth Y1", fmt(fl.get("growth_y1"), "pct"))]
        if fl.get("recovery_pct") is not None:
            rows.append(("Recovery", fmt(fl["recovery_pct"], "pct")))
        cards.append(html.Div([html.Div(["First-line package", tip(f"{fl.get('prepared_by')}, {fl.get('valuation_date')}. "
                                                                  "These are the assumptions the second line challenges.")],
                                        className="mini-label"),
                               html.Dl([x for k, v in rows for x in (html.Dt(k), html.Dd(v))], className="card-dl")], className="card"))
    data = _data_viewer(case, t) if pulled else None
    nxt = _next("Earnings", f"/case/{case['id']}/earnings") if pulled else None
    return html.Div([step_head("Scope", [badge(t["tagline"])], action), html.Div(cards, className="cards"), data, nxt])


USED_TABLES = {
    "performing": [("Borrower", ["financials", "projections", "ebitda_adjustments", "capital_structure"]),
                   ("Market", ["trading_comps", "precedent_transactions", "rates"])],
    "troubled": [("Borrower", ["financials", "ebitda_adjustments", "assets", "capital_structure"]),
                 ("Market", ["distressed_transactions", "recovery_rates"])],
}
HIDE_COLS = ("borrower_id", "sector", "case")


def _data_viewer(case, t):
    """One tabbed viewer for the pulled data: each table in full, with its source and a CSV download."""
    tables = service.pulled_tables(case["id"])
    cid = case["id"]
    tabs = []
    for group, names in USED_TABLES.get(t["id"], [("Data", list(tables))]):
        for name in names:
            df = tables.get(name)
            if df is None:
                continue
            label, code = TABLES.get(name, (name, name))
            as_of = df["as_of"].iloc[0] if "as_of" in df.columns and len(df) else None
            show = df.drop(columns=[c for c in (*HIDE_COLS, "as_of") if c in df.columns])
            caption = html.Div([
                html.Span(group, className="badge"),
                html.Span(code, className="src"),
                html.Span(f"{len(df)} rows" + (f" · as of {as_of}" if as_of else ""), className="muted small"),
                html.A("CSV", href=f"/files/data/{cid}/{name}.csv", className="btn small", style={"marginLeft": "auto"}),
            ], className="chips", style={"margin": "12px 0 8px"})
            tabs.append(dcc.Tab(label=f"{label}", value=name, className="dtab", selected_className="dtab-on",
                                children=[caption, df_table(show, max_rows=200)]))
    first = tabs[0].value if tabs else None
    return html.Div([
        html.Div([html.Div([html.H3("Pulled data", className="panel-title"),
                            html.Span(f"{case['data_source']} · {_ts(case['data_pulled_at'])}", className="muted small"),
                            tip("Only the tables this workflow uses are shown. The workbook download holds every table plus the "
                                "case inputs with their sources.")], className="chips"),
                  html.A("Download all (.xlsx)", href=f"/files/data/{cid}.xlsx", className="btn small")],
                 className="step-head", style={"marginBottom": "4px"}),
        dcc.Tabs(tabs, value=first, className="dtabs", parent_className="dtabs-wrap"),
    ], className="panel", style={"paddingTop": "16px"})


# ── 2 earnings ───────────────────────────────────────────────────────

def _bridge_for(case) -> dict | None:
    from valor.engine.review import earnings_bridge
    if not case["data_pulled_at"]:
        return None
    return earnings_bridge(service.input_values(case["id"]), case["extras"].get("addbacks", []))


def _earnings(case, t, uid, ctx):
    e = _bridge_for(case)
    if e is None:
        return empty_state("Pull the data first", _next("Scope", f"/case/{case['id']}/scope"))
    editable = _editable(case)
    haircut = e["management_adjusted"] - e["normalized"]
    fl = (case["extras"].get("first_line") or {}).get("ebitda_used")
    cap = settings()["policy"]["addback_cap"]
    v = service.input_values(case["id"])
    if t["conclusion"] == "enterprise_value":
        mult, mult_label = v.get("comps_mid"), "peer median"
    else:
        lo, hi = v.get("dist_mult_low"), v.get("dist_mult_high")
        mult, mult_label = ((lo + hi) / 2 if lo and hi else None), "distressed multiple"
    effect = f"≈ {money(haircut * mult)} of value at {mult:.1f}x {mult_label}" if mult and haircut else ""
    stat = kpis([("Reported", money(e["reported"]), "LTM"),
                 ("Management adjusted", money(e["management_adjusted"]), f"1st line used {money(fl)}" if fl else "all add-backs"),
                 ("Normalized", money(e["normalized"]), "second line", "accent"),
                 ("Haircut", money(haircut), effect or ((pct(haircut / e["management_adjusted"]) + " of adjusted")
                                                         if e["management_adjusted"] else ""), "bad" if haircut > 0 else ""),
                 ("Add-backs / reported", pct(e["accepted_share_of_reported"]), f"cap {pct(cap)}",
                  "bad" if (e["accepted_share_of_reported"] or 0) > cap else "")])
    rows = [html.Div([html.Span("Add-back"), html.Span("Claimed", className="r"), html.Span("Accepted"), html.Span("", className="r"),
                      html.Span("Counts", className="r")], className="bridge-row head")]
    for r in e["rows"]:
        rows.append(html.Div([
            html.Span([r["description"], " ", badge(r["category"].replace("_", " ")), tip(f"Support: {r['support']}")]),
            html.Span(money(r["amount"]), className="r"),
            html.Div(html.Span(style={"width": f"{r['accepted_pct'] * 100:.0f}%"}), className="accept-bar", title=pct(r["accepted_pct"])),
            html.Span(html.Button(pct(r["accepted_pct"]), id={"type": "adj-open", "key": f"addback.{r['adj_id']}"}, className="btn small")
                      if editable else pct(r["accepted_pct"]), className="r"),
            html.Span(money(r["accepted"]), className="r"),
        ], className="bridge-row"))
    rows.append(html.Div([html.Span("Normalized EBITDA"), html.Span(money(e["claimed"]), className="r"), html.Span(""), html.Span(""),
                          html.Span(money(e["normalized"]), className="r")], className="bridge-row total"))
    return html.Div([
        step_head("Earnings"),
        html.P("Decide how much of management's EBITDA add-backs to believe. The result, normalized EBITDA, is the earnings figure "
               "every multiple is applied to.", className="step-lede"),
        stat,
        html.Div([dcc.Graph(figure=charts.earnings_bridge(e), config={"displayModeBar": False})], className="panel", style={"paddingTop": "14px"}),
        html.Div(rows, className="panel", style={"paddingTop": "6px"}),
        _next("Assumptions", f"/case/{case['id']}/assumptions"),
    ])


# ── 3 assumptions ────────────────────────────────────────────────────

FEEDS = {"dcf": "DCF", "trading_comps": "Comps", "precedents": "Precedents", "liquidation": "Liquidation",
         "distressed_gc": "Distressed GC", "conclusion": "Conclusion", "downside": "Downside", "reserve": "Reserve",
         "waterfall": "Waterfall", "earnings": "Earnings"}
SERIES = {"g_y": "Revenue growth", "m_y": "EBITDA margin"}


def _adj_btn(key: str, label="Adjust", cls="btn small"):
    return html.Button(label, id={"type": "adj-open", "key": key}, className=cls)


def _input_row(i: dict, editable: bool) -> html.Div:
    adjusted = i["value"] != i["source_value"]
    delta = fmt(i["value"] - i["source_value"], i["unit"], signed=True) if adjusted else None
    return html.Div([
        html.Div([html.Span(i["label"], className="in-label"), tip(i["source_ref"])], className="in-name"),
        html.Div(fmt(i["source_value"], i["unit"]), className="in-src", title="Source value"),
        html.Div(fmt(i["value"], i["unit"]), className="in-val"),
        html.Div(html.Span(delta, className="in-delta") if delta else None),
        html.Div(_adj_btn(i["key"]) if editable else None, className="in-act"),
    ], className=f"in-row {'adjusted' if adjusted else ''}")


def _series_grid(rows: list[dict], editable: bool) -> html.Div:
    """Year-by-year inputs (growth, margin) as one row of Y1–Y5 cells each."""
    out = [html.Div([html.Span(""), *[html.Span(f"Y{y}", className="ser-h") for y in range(1, 6)]], className="ser-row head")]
    by = {i["key"]: i for i in rows}
    for prefix, label in SERIES.items():
        cells = []
        for y in range(1, 6):
            i = by.get(f"{prefix}{y}")
            if not i:
                continue
            adjusted = i["value"] != i["source_value"]
            content = [html.Div(fmt(i["value"], i["unit"]), className="ser-val"),
                       html.Div(f"was {fmt(i['source_value'], i['unit'])}" if adjusted else "management", className="ser-src")]
            cell_cls = f"ser-cell {'adjusted' if adjusted else ''}"
            cells.append(html.Button(content, id={"type": "adj-open", "key": i["key"]}, className=cell_cls + " editable",
                                     title=f"{i['label']} · adjust") if editable else html.Div(content, className=cell_cls))
        if cells:
            src = by.get(f"{prefix}1", {}).get("source_ref", "")
            out.append(html.Div([html.Div([html.Span(label, className="in-label"), tip(src.replace("year 1", "years 1–5"))], className="in-name"),
                                 *cells], className="ser-row"))
    return html.Div(out, className="series")


def _weights_bar(rows: list[dict], t: dict) -> html.Div:
    total = sum(i["value"] for i in rows)
    colors = ["var(--primary-700)", "var(--primary-600)", "#7fa8c9", "var(--brass-500)"]
    segs = [html.Span(f"{i['label'].replace('Weight, ', '')[:1].upper()}{i['label'].replace('Weight, ', '')[1:]} {pct(i['value'])}",
                      style={"width": f"{max(i['value'], 0) / max(total, 1e-9) * 100:.1f}%", "background": colors[n % len(colors)]})
            for n, i in enumerate(rows)]
    ok = abs(total - 1) < 1e-6
    return html.Div([html.Div(segs, className="wbar"),
                     html.Div([rag_chip("green" if ok else "red", f"Total {pct(total)}" + ("" if ok else " · must be 100%"))],
                              style={"marginTop": "8px"})], style={"marginBottom": "10px"})


def _assumptions(case, t, uid, ctx):
    if not case["data_pulled_at"]:
        return empty_state("Pull the data first", _next("Scope", f"/case/{case['id']}/scope"))
    inputs = service.get_inputs(case["id"])
    editable = _editable(case)
    adj = service.adjustments(case["id"])

    # changes first: what the reviewer will want to see
    pinned = _section(f"Your changes ({len(adj)})", [
        html.Div([html.Div([html.Div(a["label"], className="card-title"),
                            html.Div([fmt(a["source_value"], a["unit"]), " → ", html.B(fmt(a["value"], a["unit"]))], className="chg"),
                            html.Div(a["rationale"] or "", className="why"),
                            html.Div(f"{who(a['actor'])} · {_ts(a['ts'])}" + (" · via agent" if a["via_agent"] else ""), className="who")],
                           className="card adj-card accent") for a in adj], className="cards wide", style={"marginBottom": "0"}),
    ], tip_text="Every input that differs from its source, with the rationale recorded in the audit trail.") if adj else \
        html.Div([html.Span("No changes yet. ", className="card-title"),
                  html.Span("All inputs are at their source values; adjust any of them below." if editable else
                            "All inputs are at their source values.", className="muted small")], className="card", style={"marginBottom": "20px"})

    # the workbench: one section card per input group
    sections = []
    for g in t["input_groups"]:
        if g.get("dynamic") == "ebitda_adjustments":
            n = sum(1 for i in inputs if i["grp"] == g["id"])
            sections.append(html.Div([html.Div([html.Span(g["label"], className="card-title"),
                                                html.Span(f" {n} add-backs, reviewed in Earnings", className="muted small")]),
                                      _next("Earnings", f"/case/{case['id']}/earnings")],
                                     className="card", style={"display": "flex", "justifyContent": "space-between", "alignItems": "center",
                                                              "marginBottom": "20px"}))
            continue
        rows = [i for i in inputs if i["grp"] == g["id"]]
        if not rows:
            continue
        n_adj = sum(1 for i in rows if i["value"] != i["source_value"])
        feeds = sorted({f for i in rows for f in (i["used_by"] or "").split(",") if f})
        chips = [badge(f"{len(rows)} inputs"), badge(f"{n_adj} adjusted", "accent") if n_adj else None,
                 *[html.Span(FEEDS.get(f, f), className="badge") for f in feeds]]
        series_keys = [i for i in rows if i["key"][:3] in SERIES]
        other = [i for i in rows if i not in series_keys]
        body = []
        if g["id"] == "weights":
            body.append(_weights_bar(rows, t))
        if series_keys:
            body.append(_series_grid(series_keys, editable))
        if other:
            body.append(html.Div([html.Div([html.Span("Input"), html.Span("Source", className="r"), html.Span("In use", className="r"),
                                            html.Span(""), html.Span("")], className="in-row head"),
                                  *[_input_row(i, editable) for i in other]], className="in-table"))
        sections.append(html.Div([
            html.Div([html.Div([html.H3(g["label"], className="panel-title"), tip(g["note"]) if g.get("note") else None], className="chips"),
                      html.Div(chips, className="chips")], className="step-head", style={"marginBottom": "10px"}),
            *body,
        ], className="panel", style={"paddingTop": "16px"}, id=f"grp-{g['id']}"))

    return html.Div([
        step_head("Assumptions", [tip("Every input shows its source value. Every change needs a rationale and goes to the audit trail and memo.")],
                  html.Button("Run valuation", id=act("run"), className="btn primary") if editable else None),
        pinned,
        html.Div("Workbench", className="eyebrow", style={"margin": "4px 0 10px"}),
        *sections,
        html.Div(_next("Valuation", f"/case/{case['id']}/valuation"), style={"marginTop": "4px"}),
    ])


# ── 4 valuation ──────────────────────────────────────────────────────

def _loan_cards_performing(res, c, pol) -> list[tuple]:
    out = []
    ahead, exp = c.get("debt_ahead", 0.0), c["bank_exposure"]
    through = ahead + exp
    dsd = res.get("downside")

    def headroom_ltv(ev, limit):          # EV can fall this far before LTV breaches the limit
        return 1 - through / (limit * ev) if ev else None

    def headroom_cov(ev, minimum):        # ... before coverage drops below the minimum
        return 1 - (ahead + minimum * exp) / ev if ev else None

    if dsd:
        sh = dsd["shocks"]
        base_m = {m["method"]: m for m in res["methods"]}
        rows = [{"m": d["label"], "b": money(base_m[d["method"]]["mid"]), "d": money(d["mid"]),
                 "chg": pct(d["mid"] / base_m[d["method"]]["mid"] - 1, signed=True)} for d in dsd["methods"]]
        rows.append({"m": "Reconciled", "b": money(c["mid"]), "d": money(dsd["mid"]), "chg": pct(dsd["mid"] / c["mid"] - 1, signed=True)})
        body = [
            html.Div("Shocks applied to every method", className="eyebrow"),
            _kv_table([("EBITDA (and projected margins)", f"{sh['stress_ebitda'] * 100:+.0f}%"),
                       ("Market multiples (comps and precedents)", f"{sh['stress_multiple']:+.1f}x"),
                       ("Discount rate (via the risk-free rate)", f"{sh['stress_wacc'] * 100:+.1f}pt")]),
            html.Div("Value by method, base vs downside", className="eyebrow", style={"marginTop": "14px"}),
            table([("m", "Method", ""), ("b", "Base", "num"), ("d", "Downside", "num"), ("chg", "Change", "num")], rows,
                  row_class=lambda r: "total" if r["m"] == "Reconciled" else ""),
            html.Div("Loan metrics", className="eyebrow", style={"marginTop": "14px"}),
            table([("k", "", ""), ("b", "Base", "num"), ("d", "Downside", "num")],
                  [{"k": "Loan-to-value", "b": pct(c.get("ltv_mid")), "d": pct(dsd.get("ltv_mid"))},
                   {"k": "Coverage of commitment", "b": f"{c['coverage_mid']:.2f}x", "d": f"{dsd['coverage_mid']:.2f}x"}]),
            html.P("Shocks are inputs in the Assumptions step (Downside case), so changing them is audited like any other input.",
                   className="muted small", style={"marginTop": "10px"}),
        ]
        out.append(_expandable("sheet-downside", "Downside case", "Stress test", [("Downside EV", money(dsd["mid"])), ("Base", money(c["mid"]))], body,
                               [html.Div("Downside enterprise value", className="mini-label"), html.Div(money(dsd["mid"]), className="big"),
                                html.Div(f"EBITDA {sh['stress_ebitda'] * 100:+.0f}%, multiples {sh['stress_multiple']:+.1f}x, "
                                         f"WACC {sh['stress_wacc'] * 100:+.1f}pt", className="card-metric")], "card accent", "How it holds up"))

    for t in res.get("policy_tests") or []:
        is_pct = t["unit"] == "pct"
        f = (lambda v: pct(v)) if is_pct else (lambda v: f"{v:.2f}x")
        lim = ("≤ " if t["kind"] == "max" else "≥ ") + f(t["limit"])
        if t["id"] in ("ltv", "ltv_downside"):
            src = c if t["id"] == "ltv" else dsd
            ev_rows = [(side, src[side], src.get(f"ltv_{side}")) for side in ("low", "mid", "high")]
            head = headroom_ltv(src["mid"], t["limit"])
            formula = "Loan-to-value = (debt ranking ahead of the bank + bank commitment) ÷ enterprise value"
            calc = [("Debt ranking ahead of the bank", money(ahead)), ("Bank commitment", money(exp)), ("Debt through the bank", money(through)),
                    ("Enterprise value (mid)" + (", downside" if t["id"] != "ltv" else ""), money(src["mid"])),
                    ("Loan-to-value", f(t["value"])), ("Policy limit", lim)]
        else:
            ev_rows = [(side, c[side], c.get(f"coverage_{side}")) for side in ("low", "mid", "high")]
            head = headroom_cov(c["mid"], t["limit"])
            formula = "Coverage = (enterprise value − debt ranking ahead of the bank) ÷ bank commitment"
            calc = [("Enterprise value (mid)", money(c["mid"])), ("Debt ranking ahead of the bank", money(ahead)),
                    ("Value available to the bank", money(c["mid"] - ahead)), ("Bank commitment", money(exp)),
                    ("Coverage", f(t["value"])), ("Policy minimum", lim)]
        head_txt = (f"Enterprise value can fall {pct(head)} before this test fails." if head and head > 0
                    else "Already outside the limit.")
        body = [
            html.P(formula, className="small"),
            _kv_table(calc),
            html.Div("Across the valuation range", className="eyebrow", style={"marginTop": "14px"}),
            table([("s", "Case", ""), ("ev", "Enterprise value", "num"), ("m", t["label"], "num")],
                  [{"s": side.capitalize(), "ev": money(ev), "m": f(m) if m is not None else "—"} for side, ev, m in ev_rows]),
            html.Div([html.Div("Headroom", className="mini-label"), html.Div(head_txt, className="card-title")],
                     className=f"card {'pass' if t['pass'] else 'fail'}", style={"marginTop": "14px"}),
        ]
        out.append(_expandable(f"sheet-{t['id']}", t["label"], "Policy test", [("Value", f(t["value"])), ("Limit", lim)], body,
                               [html.Div(t["label"], className="mini-label"), html.Div(f(t["value"]), className="big"),
                                html.Div(lim + (" · pass" if t["pass"] else " · FAIL"), className="card-metric")],
                               f"card {'pass' if t['pass'] else 'fail'}", "Headroom"))
    return out


def _loan_cards_troubled(res, c, case) -> list[tuple]:
    rv = res.get("reserve") or {}
    exp = c["bank_exposure"]
    out = []
    pv_body = [
        html.P("Recoveries arrive over time, so they are discounted to today at the loan's effective interest rate.", className="small"),
        _kv_table([("Time to recovery", f"{rv.get('years', 0):g} years"), ("Discount rate (loan effective rate)", pct(rv.get("rate"))),
                   ("Discount factor  1 ÷ (1 + rate)^years", f"{rv.get('pv_factor', 0):.4f}")]),
        html.Div("Recovery and its present value", className="eyebrow", style={"marginTop": "14px"}),
        table([("s", "Case", ""), ("r", "Recovery", "num"), ("pv", "Present value", "num")],
              [{"s": side.capitalize(), "r": money(c[side]), "pv": money(rv.get(f"pv_{side}"))} for side in ("low", "mid", "high")]),
        html.P("Time to recovery and the discount rate are inputs (Recovery timing), so changes are audited.", className="muted small",
               style={"marginTop": "10px"}),
    ]
    out.append(_expandable("sheet-pv", "PV of recovery", "Discounting", [("PV (mid)", money(rv.get("pv_mid"))), ("Recovery", money(c["mid"]))],
                           pv_body,
                           [html.Div("PV of recovery", className="mini-label"), html.Div(money(rv.get("pv_mid")), className="big"),
                            html.Div(f"{rv.get('years', 0):g} years at {pct(rv.get('rate'))}", className="card-metric")], "card", "The maths"))
    first = c.get("first_line_value") or 0
    fl_reserve = max(0.0, exp - first) if first else None
    res_body = [
        html.P("Specific reserve = bank exposure − present value of the expected recovery (floored at zero).", className="small"),
        table([("s", "Case", ""), ("pv", "PV of recovery", "num"), ("r", "Reserve", "num"), ("p", "% of exposure", "num")],
              [{"s": f"{side.capitalize()} recovery", "pv": money(rv.get(f"pv_{side}")), "r": money(rv.get(f"reserve_{side}")),
                "p": pct(rv.get(f"reserve_{side}", 0) / exp) if exp else "—"} for side in ("low", "mid", "high")]),
        html.Div("Against the first line", className="eyebrow", style={"marginTop": "14px"}),
        _kv_table([("First-line recovery estimate (undiscounted)", money(first)),
                   ("Reserve implied by the first line", money(fl_reserve) if fl_reserve is not None else "—"),
                   ("Second-line reserve (mid)", money(rv.get("reserve_mid"))),
                   ("Difference", money(rv.get("reserve_mid", 0) - (fl_reserve or 0)) if fl_reserve is not None else "—")]),
        html.P("The first line's estimate is not discounted, so its implied reserve is understated by the time value of the recovery.",
               className="muted small", style={"marginTop": "10px"}) if first else None,
    ]
    out.append(_expandable("sheet-reserve", "Specific reserve", "Impairment",
                           [("Reserve (mid)", money(rv.get("reserve_mid"))), ("% of exposure", pct(rv.get("reserve_pct_mid")))], res_body,
                           [html.Div("Specific reserve", className="mini-label"), html.Div(money(rv.get("reserve_mid")), className="big"),
                            html.Div(f"{pct(rv.get('reserve_pct_mid'))} of exposure · range {money(min(rv['reserve_range']))} – "
                                     f"{money(max(rv['reserve_range']))}" if rv else "", className="card-metric")], "card fail", "How it's built"))
    claims = [{"p": cl["priority"], "c": ("◆ " if cl["bank_share"] > 0 else "") + cl["claim_class"],
               "a": money(service.input_values(case["id"]).get(f"claim.{cl['claim_id']}"))} for cl in case["claims"]]
    ex_body = [html.P("Claims paid in order of priority; equal priorities share pro rata. ◆ marks the bank's claim.", className="small"),
               table([("p", "Priority", "num"), ("c", "Claim", ""), ("a", "Amount", "num")], claims)]
    out.append(_expandable("sheet-exposure", "Exposure", "Claims stack", [("Bank exposure", money(exp))], ex_body,
                           [html.Div("Exposure", className="mini-label"), html.Div(money(exp), className="big"),
                            html.Div("outstanding", className="card-metric")], "card", "Claims stack"))
    return out



def _valuation(case, t, uid, ctx):
    run = ctx["run"]
    run_btn = None
    if _editable(case) and case["data_pulled_at"]:
        run_btn = html.Button("Re-run" if run else "Run valuation", id=act("run"),
                              className="btn primary" if not run or not ctx["current"] else "btn small")
    if not run:
        return html.Div([step_head("Valuation"), empty_state("No valuation yet", run_btn)])
    res = run["results"]
    c = res["conclusion"]
    vs = c.get("vs_first_line")
    rag_tone = {"red": "bad", "green": "good"}.get(c.get("rag"), "")
    pol = settings()["policy"]
    performing = c["measure"] == "enterprise_value"

    # 1 · the answer
    if performing:
        strip = kpis([("Enterprise value", money(c["mid"]), f"{money(c['low'])} – {money(c['high'])}", "accent"),
                      ("vs first line", pct(vs, signed=True) if vs is not None else "—", f"1st line {money(c['first_line_value'])}", rag_tone),
                      ("Loan-to-value", pct(c.get("ltv_mid")), f"limit {pct(pol['max_ltv'])}"),
                      ("Coverage", f"{c['coverage_mid']:.2f}x" if c.get("coverage_mid") else "—", f"min {pol['min_coverage']:.1f}x")])
    else:
        rv = res.get("reserve") or {}
        strip = kpis([("Bank recovery", money(c["mid"]), f"{money(c['low'])} – {money(c['high'])}", "accent"),
                      ("vs first line", pct(vs, signed=True) if vs is not None else "—", f"1st line {money(c['first_line_value'])}", rag_tone),
                      ("Recovery rate", pct(c.get("recovery_pct_mid")), f"of {money(c['bank_exposure'])}"),
                      ("Specific reserve", money(rv.get("reserve_mid")),
                       f"{money(min(rv['reserve_range']))} – {money(max(rv['reserve_range']))}" if rv else "", "bad")])

    # 2 · how the value is built
    span_hi = max([m["high"] for m in res["methods"]] + [c["high"], c.get("first_line_value") or 0]) * 1.05 or 1
    tables = service.pulled_tables(case["id"])
    mcards, sheets = [], []
    for m in res["methods"]:
        card, sheet = _expandable(
            f"sheet-{m['method']}", m["label"], "Workings",
            [("Mid", money(m["mid"])), ("Range", f"{money(m['low'])} – {money(m['high'])}")],
            _method_body(m, tables),
            [html.Div([html.Span(m["label"], className="card-title"), html.Span(f"weight {pct(m['details'].get('weight'))}", className="muted small")],
                      className="card-top"),
             html.Div(money(m["mid"]), className="big", style={"marginTop": "8px"}),
             html.Div(f"{money(m['low'])} – {money(m['high'])}", className="range"),
             html.Div([html.Span(style={"left": f"{m['low'] / span_hi * 100:.1f}%", "width": f"{(m['high'] - m['low']) / span_hi * 100:.1f}%"}),
                       html.I(style={"left": f"{m['mid'] / span_hi * 100:.1f}%"})], className="bar")],
            "card method-card", "View workings")
        mcards.append(card)
        sheets.append(sheet)
    built = _section("How the value is built", [
        dcc.Graph(figure=charts.football_field(res["methods"], c), config={"displayModeBar": False}),
        html.Div(mcards, className="cards", style={"marginBottom": "0"}),
    ], tip_text="Each method's low–high range; the reconciled range is their weighted average. Dashed lines mark the first line's "
                "value and the debt through the bank. Click any card for its detail.")

    # 3 · what it means for the loan (each card opens its detail)
    loan_cards = []
    if performing:
        for card, sheet in _loan_cards_performing(res, c, pol):
            loan_cards.append(card)
            sheets.append(sheet)
        tip_loan = "Collateral coverage in the base and downside cases, tested against policy limits (config/settings.yaml)."
    else:
        for card, sheet in _loan_cards_troubled(res, c, case):
            loan_cards.append(card)
            sheets.append(sheet)
        tip_loan = "Reserve = exposure − present value of the expected recovery."
    loan = _section("What it means for the loan", [html.Div(loan_cards, className="cards", style={"marginBottom": "0"})], tip_text=tip_loan)

    # 4 · what to look at: agent commentary + review checks
    regen = html.Button("Regenerate", id=act("explain"), className="btn link small")
    poll = None
    if run.get("explanation"):
        commentary = html.Div([html.Div(run["explanation"], className="agent-voice"),
                               html.Div([f"Agent ({run['explanation_source']}) · run #{run['id']}", regen], className="agent-meta chips")])
    else:
        service.explain_async(case["id"])
        if service.explanation_pending(run["id"]):
            commentary = html.Div([html.Span(className="busy-dot", style={"display": "inline-block", "marginRight": "10px"}),
                                   "The agent is writing the commentary…"], className="muted small", style={"display": "flex", "alignItems": "center"})
            poll = dcc.Interval(id="explain-poll", interval=2500, max_intervals=80)
        else:
            commentary = html.Div(["No commentary for this run. ", html.Button("Write it now", id=act("explain"), className="btn small")])
    checks = sorted(run["checks"] or [], key=lambda x: ["high", "medium", "low"].index(x["severity"]))
    check_list = html.Div([html.Div([html.Div([badge(x["severity"], "bad" if x["severity"] == "high" else "warn" if x["severity"] == "medium" else ""),
                                               " ", html.Span(x["title"], className="card-title")]),
                                     html.Div(x["detail"], className="card-metric")], className=f"card sev-{x['severity']}")
                           for x in checks], className="risk-list") if checks else html.P("No checks raised.", className="muted small")
    look = html.Div([
        _section("Agent commentary", [commentary, poll], tip_text="Written by Claude from the engine's results after each run. It quotes "
                                                                  "only engine figures; it never produces a number of its own."),
        _section(f"Review checks ({len(checks)})", [check_list], tip_text="Deterministic rules the agent also reasons over."),
    ], className="grid-2")

    return html.Div([
        step_head("Valuation", [html.Span(f"Run #{run['id']} · {who(run['actor'])} · {_ts(run['ts'])}", className="muted small"),
                                tip(f"Inputs hash {run['inputs_hash']}. All figures from the deterministic engine; USD millions.")], run_btn),
        None if ctx["current"] else html.Div("Inputs changed since this run. Re-run to update.", className="statusline review"),
        strip, built, loan, look,
        whatif_panel(case, uid),
        *sheets,                       # overlays live outside animated panels so they cover the whole viewport
        html.Div(_next("Challenge", f"/case/{case['id']}/challenge"), style={"marginTop": "16px"}),
    ])


def whatif_panel(case, uid) -> html.Div:
    """Sandbox: override inputs and see the effect. Nothing is saved. A reviewer can turn it into challenges."""
    me = user(uid)
    inputs = service.get_inputs(case["id"])
    opts = [{"label": f"{i['label']} · {fmt(i['value'], i['unit'])}", "value": i["key"]} for i in inputs]
    can_challenge = case["status"] == "submitted" and me["role"] in ("reviewer", "admin") and \
        (uid != case["submitted_by"] or settings()["review"]["allow_self_approval"])
    challenge = html.Div([
        html.Div([html.Label("Challenge for the analyst"),
                  dcc.Textarea(id="whatif-comment", className="inp", style={"minHeight": "64px"},
                               placeholder="Why these values? The analyst must accept each challenge or answer it.")],
                 className="field", style={"marginTop": "14px"}),
        html.Button("Send back with these challenges", id="whatif-sendback", className="btn primary"),
    ]) if can_challenge else None
    return html.Div([
        dcc.Store(id="whatif-mount", data=case["id"]),
        html.Div([html.Div([html.H3("What-if", className="panel-title"), badge("not saved"),
                            tip("Change any assumption and see the effect on value, policy and the suggested verdict. The case of "
                                "record does not change." + (" As the reviewer you can send these back as formal challenges."
                                                             if can_challenge else ""))], className="chips"),
                  html.Button("Clear", id="whatif-clear", className="btn small")], className="step-head", style={"marginBottom": "10px"}),
        html.Div([
            html.Div(dcc.Dropdown(id="whatif-key", options=opts, placeholder="Choose an assumption…"), style={"flex": "1 1 340px"}),
            dcc.Input(id="whatif-value", className="inp", placeholder="New value", style={"width": "140px"}),
            html.Button("Try it", id="whatif-add", className="btn"),
        ], className="btn-row"),
        html.Div(id="whatif-unit", className="help small muted", style={"marginTop": "4px"}),
        html.Div(id="whatif-list", style={"marginTop": "10px"}),
        html.Div(id="whatif-result"),
        challenge,
    ], className="panel", id="whatif", style={"paddingTop": "16px"})


def whatif_result(case_id: str, overrides: dict) -> tuple:
    if not overrides:
        return None, html.P("Pick an assumption, enter a value and press Try it.", className="muted small")
    rows = {r["key"]: r for r in service.get_inputs(case_id)}
    chips = html.Div([html.Span([rows[k]["label"], ": ", fmt(rows[k]["value"], rows[k]["unit"]), " → ", html.B(fmt(v, rows[k]["unit"])),
                                 html.Button("×", id={"type": "whatif-rm", "key": k}, className="btn link small", title="Remove")],
                                className="badge accent", style={"padding": "3px 4px 3px 8px"}) for k, v in overrides.items() if k in rows],
                     className="chips")
    try:
        w = service.what_if(case_id, overrides)
    except service.ReviewError as e:
        return chips, html.Div(str(e), className="notice bad")
    b, a = w["base"], w["what_if"]

    def delta(x, y, kind="money"):
        if x is None or y is None:
            return ""
        d = y - x
        if abs(d) < 1e-9:
            return "—"
        return pct(d, signed=True).replace("%", "pt") if kind == "pt" else (f"{d:+.2f}x" if kind == "x" else f"{d:+,.1f}")
    lines = [("Normalized EBITDA", money(b["normalized_ebitda"]), money(a["normalized_ebitda"]), delta(b["normalized_ebitda"], a["normalized_ebitda"])),
             ("Value (mid)", money(b["mid"]), money(a["mid"]), delta(b["mid"], a["mid"])),
             ("Range", f"{money(b['low'])} – {money(b['high'])}", f"{money(a['low'])} – {money(a['high'])}", ""),
             ("vs first line", rag_chip(b["rag"], pct(b["vs_first_line"], signed=True)), rag_chip(a["rag"], pct(a["vs_first_line"], signed=True)), "")]
    if b["measure"] == "enterprise_value":
        lines += [("Loan-to-value", pct(b["ltv"]), pct(a["ltv"]), delta(b["ltv"], a["ltv"], "pt")),
                  ("Coverage", f"{b['coverage']:.2f}x", f"{a['coverage']:.2f}x", delta(b["coverage"], a["coverage"], "x")),
                  ("Downside value", money(b["downside"]), money(a["downside"]), delta(b["downside"], a["downside"]))]
    else:
        lines += [("Recovery rate", pct(b["recovery_pct"]), pct(a["recovery_pct"]), delta(b["recovery_pct"], a["recovery_pct"], "pt")),
                  ("Specific reserve", money(b["reserve"]), money(a["reserve"]), delta(b["reserve"], a["reserve"]))]
    lines += [("Policy breaches", ", ".join(b["policy_fail"]) or "None", ", ".join(a["policy_fail"]) or "None", ""),
              ("Rules suggest", verdict_chip(b["suggested_verdict"]), verdict_chip(a["suggested_verdict"]), "")]
    tbl = table([("m", "", ""), ("b", "Case of record", "num"), ("a", "What-if", "num"), ("d", "Change", "num")],
                [{"m": m, "b": x, "a": html.B(y) if isinstance(y, str) else y, "d": d} for m, x, y, d in lines])
    return chips, html.Div(tbl, style={"marginTop": "10px"})


def _peer_table(df, mult: list[float], label_col: str):
    if df is None or df.empty:
        return None
    lo, hi = mult[0], mult[-1]
    d = df.sort_values("ev_ebitda", ascending=False)
    rows = [{"n": r[label_col], "m": f"{r['ev_ebitda']:.1f}x", "in": "within range" if lo <= r["ev_ebitda"] <= hi else ""}
            for _, r in d.iterrows()]
    return html.Div([html.Div(f"Peer set ({len(d)})", className="eyebrow", style={"margin": "10px 0 4px"}),
                     table([("n", "Company" if label_col == "company_name" else "Target", ""), ("m", "EV / EBITDA", "num"),
                            ("in", "", "")], rows, row_class=lambda r: "" if r["in"] else "muted")])


def _method_body(m: dict, tables: dict) -> list:
    d = m["details"]
    chip = lambda t: html.Span(t, className="badge")  # noqa: E731
    if m["method"] == "dcf":
        w = d["wacc"]
        proj = [{"year": p["year"], **{k: money(p[k]) for k in ("revenue", "ebitda", "ebit", "taxes", "capex", "change_nwc", "fcf")}}
                for p in d["projection"]]
        sens = d["sensitivity"]
        sens_rows = [{"w": pct(wv), **{f"g{j}": money(sens['ev'][i][j]) for j in range(len(sens['growth']))}}
                     for i, wv in enumerate(sens["wacc"])]
        return [
            html.Div([chip(f"WACC {pct(w['wacc'])}"), chip(f"Levered beta {w['levered_beta']:.2f}"), chip(f"Cost of equity {pct(w['cost_of_equity'])}"),
                      chip(f"PV of cash flows {money(d['pv_fcf'])}"), chip(f"PV of terminal value {money(d['pv_terminal'])} ({pct(d['terminal_share'])})"),
                      chip(f"Implied exit {d['implied_exit_multiple']:.1f}x")], className="chips", style={"marginBottom": "10px"}),
            html.Div("Five-year projection", className="eyebrow"),
            table([("year", "Year", "num"), ("revenue", "Revenue", "num"), ("ebitda", "EBITDA", "num"), ("ebit", "EBIT", "num"),
                   ("taxes", "Taxes", "num"), ("capex", "Capex", "num"), ("change_nwc", "ΔNWC", "num"), ("fcf", "Free cash flow", "num")], proj),
            html.Div("Sensitivity: enterprise value by WACC (rows) and terminal growth (columns)", className="eyebrow", style={"marginTop": "14px"}),
            table([("w", "WACC", "num"), *[(f"g{j}", pct(g), "num") for j, g in enumerate(sens["growth"])]], sens_rows),
        ]
    if m["method"] in ("trading_comps", "precedents"):
        mult = d["multiples"]
        disc = d.get("private_discount")
        formula = (f"Normalized EBITDA {money(d['ebitda'])} × EV/EBITDA {mult[0]:.1f}x (25th) / {mult[1]:.1f}x (median) / {mult[2]:.1f}x (75th)"
                   + (f" × (1 − {pct(disc)} private-company discount)" if disc else ""))
        peers = _peer_table(tables.get("trading_comps") if m["method"] == "trading_comps" else tables.get("precedent_transactions"),
                            mult, "company_name" if m["method"] == "trading_comps" else "target")
        return [html.P(formula, className="small"), peers]
    if m["method"] == "liquidation":
        rows = [{"a": a["label"], "book": money(a["book"]), "rl": pct(a["rr_low"]), "rh": pct(a["rr_high"]),
                 "pl": money(a["proceeds_low"]), "ph": money(a["proceeds_high"])} for a in d["assets"]]
        rows.append({"a": "Less wind-down costs", "pl": money(-d["wind_down"]["low"]), "ph": money(-d["wind_down"]["high"])})
        rows.append({"a": "Net distributable", "pl": money(d["net"]["low"]), "ph": money(d["net"]["high"])})
        return [html.Div("Asset recoveries", className="eyebrow"),
                table([("a", "Asset class", ""), ("book", "Book", "num"), ("rl", "Rec. low", "num"), ("rh", "Rec. high", "num"),
                       ("pl", "Proceeds low", "num"), ("ph", "Proceeds high", "num")], rows,
                      row_class=lambda r: "total" if r["a"] == "Net distributable" else ""),
                html.Div("Recovery waterfall (◆ bank claim)", className="eyebrow", style={"marginTop": "14px"}),
                dcc.Graph(figure=charts.waterfall_chart(m), config={"displayModeBar": False}), _waterfall_table(d)]
    if m["method"] == "distressed_gc":
        return [html.P(f"Normalized EBITDA {money(d['ebitda'])} × distressed EV/EBITDA {d['multiples'][0]:.1f}x – {d['multiples'][1]:.1f}x "
                       f"= {money(d['ev']['low'])} – {money(d['ev']['high'])}, less restructuring costs: "
                       f"{money(d['distributable']['low'])} – {money(d['distributable']['high'])} distributable.", className="small"),
                _peer_table(tables.get("distressed_transactions"), d["multiples"], "target"),
                html.Div("Recovery waterfall (◆ bank claim)", className="eyebrow", style={"marginTop": "14px"}),
                dcc.Graph(figure=charts.waterfall_chart(m), config={"displayModeBar": False}), _waterfall_table(d)]
    return [html.Pre(json.dumps(d, indent=1, default=str), className="code")]


def _waterfall_table(d):
    rows = []
    for lo, hi in zip(d["waterfall"]["low"]["claims"], d["waterfall"]["high"]["claims"]):
        rows.append({"c": f"{'◆ ' if lo['bank_share'] > 0 else ''}{lo['claim_class']}", "p": lo["priority"], "a": money(lo["amount"]),
                     "rl": money(lo["recovered"]), "pl": pct(lo["recovery_pct"]), "rh": money(hi["recovered"]), "ph": pct(hi["recovery_pct"])})
    return table([("c", "Claim", ""), ("p", "Priority", "num"), ("a", "Amount", "num"), ("rl", "Recovered low", "num"),
                  ("pl", "%", "num"), ("rh", "Recovered high", "num"), ("ph", "%", "num")], rows)


# ── 5 challenge ──────────────────────────────────────────────────────

def _challenge(case, t, uid, ctx):
    run = ctx["run"]
    if not run:
        return html.Div([step_head("Challenge"), empty_state("Run the valuation first", _next("Valuation", f"/case/{case['id']}/valuation"))])
    editable = _editable(case)
    comp = run["results"].get("first_line_comparison") or []
    comp_rows = [{"a": r["assumption"], "f": fmt(r["first_line"], r["unit"]), "s": fmt(r["second_line"], r["unit"]),
                  "d": (f"{r['delta'] * 100:+.2f}pt" if r["delta_kind"] == "pt" else pct(r["delta"], signed=True)) if r["delta"] is not None else "—",
                  "st": html.Span(className=f"dot {r['status']}", title=r["status"])} for r in comp]
    comparison = _section("First line vs second line", [
        table([("st", "", ""), ("a", "Assumption", ""), ("f", "First line", "num"), ("s", "Second line", "num"), ("d", "Difference", "num")], comp_rows)],
        tip_text="Each of the first line's key assumptions against the second line's. Dots: green within tolerance, amber worth "
                 "discussing, red material.") if comp else None

    recs = service.recommendations(case["id"])
    labels = {i["key"]: (i["label"], i["unit"]) for i in service.get_inputs(case["id"])}
    sev = {"high": 0, "medium": 1, "low": 2}
    open_ = sorted([r for r in recs if r["status"] == "open"], key=lambda r: sev.get(r["severity"], 3))
    done = [r for r in recs if r["status"] != "open"]

    def rec_card(r):
        lab, unit = labels.get(r["field"], (None, "musd"))
        change = None
        if r["field"]:
            change = html.Div([html.Span(["Input ", html.B(lab)]), html.Span(["Now ", html.B(fmt(r["current_value"], unit))]),
                               html.Span(["Proposed ", html.B(fmt(r["proposed_value"], unit))]) if r["proposed_value"] is not None else None],
                              className="rec-change")
        if r["status"] == "open":
            foot = html.Div([html.Button("Accept", id={"type": "rec-accept", "id": r["id"]}, className="btn small ink"),
                             html.Button("Edit", id={"type": "rec-edit", "id": r["id"]}, className="btn small") if r["field"] else None,
                             html.Button("Reject", id={"type": "rec-reject", "id": r["id"]}, className="btn small")],
                            className="btn-row rec-actions") if editable else None
        else:
            final = f" → {fmt(r['final_value'], unit)}" if r["final_value"] is not None and r["status"] == "edited" else ""
            foot = html.Div([badge(r["status"].capitalize() + final, "good" if r["status"] != "rejected" else ""),
                             f" {who(r['decided_by'])}", html.Span(f" · “{r['decision_note']}”" if r["decision_note"] else "")],
                            className="rec-decision")
        return html.Div([html.Div([badge(r["severity"], "bad" if r["severity"] == "high" else "warn" if r["severity"] == "medium" else ""),
                                   html.Span(r["title"], className="rec-title"), tip(f"#{r['id']} · {r['source']} · run {r['run_id']}")],
                                  className="rec-head"),
                         html.Div(r["rationale"], className="agent-voice", style={"fontSize": "0.9rem"}),
                         change, foot], className=f"rec {'open' if r['status'] == 'open' else ''}")

    chs = service.challenges(case["id"])
    open_ch = [x for x in chs if x["status"] == "open"]

    def ch_card(x):
        imp = x["impact"]
        b, a = imp.get("base", {}), imp.get("what_if", {})
        effect = f"Value {money(b.get('mid'))} → {money(a.get('mid'))}" if b else ""
        if b.get("rag") != a.get("rag") and a:
            effect += f" · status {b.get('rag')} → {a.get('rag')}"
        head = html.Div([badge("Reviewer challenge", "bad" if x["status"] == "open" else ""), html.Span(x["label"], className="rec-title"),
                         html.Span(f"{who(x['raised_by'])} · {_ts(x['ts'])}", className="muted small")], className="rec-head")
        change = html.Div([html.Span(["Yours ", html.B(fmt(x["analyst_value"], x["unit"]))]),
                           html.Span(["Reviewer ", html.B(fmt(x["proposed_value"], x["unit"]))]), html.Span(effect)], className="rec-change")
        if x["status"] == "open" and editable:
            foot = html.Div([dcc.Textarea(id={"type": "chal-note", "id": x["id"]}, className="inp", style={"minHeight": "48px"},
                                          placeholder="Response (required to decline, optional to accept)"),
                             html.Div([html.Button("Accept reviewer value", id={"type": "chal-accept", "id": x["id"]}, className="btn small ink"),
                                       html.Button("Decline with response", id={"type": "chal-decline", "id": x["id"]}, className="btn small")],
                                      className="btn-row", style={"marginTop": "8px"})], className="rec-actions")
        elif x["status"] == "open":
            foot = html.Div("Waiting for the analyst.", className="rec-decision")
        else:
            foot = html.Div([badge(x["status"].capitalize(), "good" if x["status"] == "accepted" else ""), f" {who(x['resolved_by'])}",
                             html.Span(f" · “{x['response']}”" if x["response"] else "")], className="rec-decision")
        return html.Div([head, html.Div(x["comment"], className="agent-voice", style={"fontSize": "0.9rem"}), change, foot],
                        className=f"rec {'open' if x['status'] == 'open' else ''}")
    challenge_block = _section(f"Reviewer challenges ({len(open_ch)} open)", [ch_card(x) for x in chs],
                               tip_text="Raised by the checker from a What-if. Accept to apply the value, or decline with a response.") if chs else None

    ask = html.Button("Ask the agent", id=act("recs"), className="btn primary") if editable else None
    stale = html.Div("Re-run the valuation to apply accepted changes.", className="statusline review") \
        if not ctx["current"] and editable else None
    return html.Div([
        step_head("Challenge", [badge(f"{len(open_)} open", "warn" if open_ else ""), badge(f"agent: {runner.mode()}"),
                                tip("Claude proposes input changes or flags; you accept, edit or reject each. It never produces a valuation figure.")],
                  html.Button("Ask again", id=act("recs"), className="btn small") if recs and editable else None),
        stale, challenge_block, comparison,
        _section(f"Agent recommendations ({len(open_)} open)", [rec_card(r) for r in open_],
                 tip_text="Accept, edit or reject each; accepted changes become audited input adjustments.") if open_ else None,
        _section(f"Decided ({len(done)})", [html.Details([html.Summary("Show decided recommendations"), *[rec_card(r) for r in done]],
                                                          className="fold", open=not open_)]) if done else None,
        None if recs else empty_state("No recommendations yet", ask),
        html.Div(_next("Opinion", f"/case/{case['id']}/opinion"), style={"marginTop": "16px"}),
    ])


# ── 6 opinion ────────────────────────────────────────────────────────

def _opinion(case, t, uid, ctx):
    run = ctx["run"]
    if not run:
        return html.Div([step_head("Opinion"), empty_state("Run the valuation first", _next("Valuation", f"/case/{case['id']}/valuation"))])
    op = case["opinion"]
    draft = case["extras"].get("opinion_draft")
    suggested = service.suggested_verdict(case["id"])
    editable = _editable(case)
    chips = [html.Span("Rules suggest", className="muted small"), verdict_chip(suggested),
             tip("From the traffic light on variance (green ≤5%, amber ≤15%, red >15%), the policy tests and high-severity checks.")]
    src = op or draft or {}
    risks = src.get("risks") or []
    questions = src.get("questions") or []
    risk_view = html.Div([
        html.Div([html.Div("Top risks", className="eyebrow", style={"marginBottom": "6px"}),
                  html.Div([html.Div([html.Div(r["risk"], className="card-title"), html.Div(["Mitigant: ", r["mitigant"]], className="card-metric")],
                                     className="card sev-medium") for r in risks], className="risk-list")]) if risks else None,
        html.Div([html.Div("Questions for the first line", className="eyebrow", style={"marginBottom": "6px"}),
                  html.Ol([html.Li(q) for q in questions], className="small", style={"paddingLeft": "18px"})]) if questions else None,
    ], className="grid-2") if (risks or questions) else None

    if not editable:
        if not op:
            return html.Div([step_head("Opinion", chips), empty_state("No opinion recorded")])
        return html.Div([step_head("Opinion", chips),
                         html.Div([verdict_chip(op["verdict"]), html.P(op["rationale"], className="agent-voice", style={"marginTop": "10px"}),
                                   html.Ul([html.Li(c) for c in op["conditions"]], className="small") if op["conditions"] else None,
                                   html.Div(f"{who(op['by'])} · {_ts(op['ts'])} · run #{op['run_id']}", className="muted small")],
                                  className="gate"), risk_view])

    stale = html.Div("The valuation was re-run after this opinion. Confirm it against the latest run.", className="statusline review") \
        if op and op["run_id"] != run["id"] else None
    draft_note = html.Div([badge(f"Drafted by agent ({draft['source']})", "accent"), " Edit before saving."], className="small",
                          style={"marginBottom": "10px"}) if draft and not op else None
    return html.Div([
        step_head("Opinion", chips, html.Button("Draft with agent", id=act("opinion-draft"), className="btn small")),
        stale,
        html.Div([
            draft_note,
            dcc.RadioItems(id=field("op-verdict"), className="verdicts", value=src.get("verdict") or suggested,
                           options=[{"label": v, "value": k} for k, v in VERDICTS.items()]),
            html.Div([html.Label("Rationale"), dcc.Textarea(id=field("op-rationale"), className="inp", value=src.get("rationale", ""),
                                                           placeholder="Why the first line's value is or is not supported")],
                     className="field", style={"marginTop": "14px"}),
            html.Div([html.Label("Conditions and exceptions (one per line)"),
                      dcc.Textarea(id=field("op-conditions"), className="inp", value="\n".join(src.get("conditions") or []),
                                   style={"minHeight": "70px"})], className="field"),
            html.Button("Save opinion", id=act("opinion-save"), className="btn primary"),
        ], className="gate"),
        risk_view,
        html.Div(_next("Approval", f"/case/{case['id']}/approval"), style={"marginTop": "16px"}),
    ])


# ── 7 approval ───────────────────────────────────────────────────────

def _approval(case, t, uid, ctx):
    me = user(uid)
    reviews = service.reviews(case["id"])
    timeline = html.Div([html.Div([html.Div([html.B({"submit": "Submitted", "send_back": "Sent back", "approve": "Approved"}[r["action"]]),
                                             f" · {who(r['actor'])}", html.Span(f" · {_ts(r['ts'])}", className="stamp")]),
                                   html.Div(r["comment"], className="small muted") if r["comment"] else None],
                                  className=f"timeline-item {r['action']}") for r in reviews]) if reviews else \
        html.P("Not submitted yet.", className="muted small")
    run = ctx["run"]
    c = run["results"]["conclusion"] if run else {}
    op = case["opinion"]
    summary = html.Div([mini("2nd line", money(c.get("mid")), pct(c.get("vs_first_line"), signed=True) if c else None),
                        mini("Adjusted inputs", str(ctx["n_adj"])),
                        html.Div([html.Div("Opinion", className="mini-label"), verdict_chip(op["verdict"] if op else None)], className="mini")],
                       className="band-stats", style={"margin": "6px 0 14px"})
    gate = None
    if case["status"] in service.EDITABLE:
        pre = [("Valuation is current", ctx["current"]), ("Recommendations decided", ctx["open_recs"] == 0),
               ("Reviewer challenges answered", ctx["open_challenges"] == 0), ("Opinion on latest run", ctx["opinion_current"])]
        ok = all(v for _, v in pre)
        gate = html.Div([
            html.H3("Submit for review", className="panel-title"), summary,
            checklist(pre),
            html.Div([html.Label("Note to the reviewer"), dcc.Textarea(id=field("review-comment"), className="inp")], className="field"),
            html.Button(f"Submit as {me['name']}", id=act("submit"), className="btn primary") if ok else
            html.Div("Complete the missing items to submit.", className="muted small"),
        ], className="gate")
    elif case["status"] == "submitted":
        can = me["role"] in ("reviewer", "admin") and (uid != case["submitted_by"] or settings()["review"]["allow_self_approval"])
        if can:
            gate = html.Div([
                html.H3("Reviewer decision", className="panel-title"), summary,
                html.Div([html.Label("Comment (required to send back)"), dcc.Textarea(id=field("review-comment"), className="inp")], className="field"),
                html.Div([html.Button("Approve and lock", id=act("approve"), className="btn primary"),
                          html.Button("Send back", id=act("sendback"), className="btn"),
                          dcc.Link("Challenge specific assumptions →", href=f"/case/{case['id']}/valuation#whatif", className="btn link")],
                         className="btn-row"),
            ], className="gate")
        else:
            why = "You submitted this case; another reviewer must check it." if uid == case["submitted_by"] else \
                f"Reviewer action needed. You are acting as {me['role']}; switch user at the top right."
            gate = html.Div([html.H3("Awaiting the checker", className="panel-title"), summary, html.P(why, className="muted small")], className="gate")
    elif case["status"] == "approved":
        gate = html.Div([html.H3("Approved and locked", className="panel-title"), summary], className="gate")
    return html.Div([step_head("Approval", [tip("Maker-checker: the analyst submits; a different person with the reviewer role approves "
                                                 "(which locks the case) or sends it back.")]),
                     html.Div([gate, _section("History", [timeline])], className="grid-2")])


# ── 8 deliver ────────────────────────────────────────────────────────

def _deliver(case, t, uid, ctx):
    if not ctx["run"]:
        return html.Div([step_head("Deliver"), empty_state("Run the valuation first", _next("Valuation", f"/case/{case['id']}/valuation"))])
    tpls = report_render.list_templates()
    rep = report_render.latest_report(case["id"])
    gen = html.Div([
        html.Div(dcc.Dropdown(id=field("rpt-template"), clearable=False, value=tpls[0]["id"] if tpls else None,
                              options=[{"label": x["name"] + (" (uploaded)" if x["uploaded"] else ""), "value": x["id"]} for x in tpls]),
                 style={"flex": "1 1 260px"}),
        dcc.Checklist(id=field("rpt-agent"), options=[{"label": " agent narrative", "value": "agent"}], value=["agent"], className="small"),
        html.Button("Generate", id=act("report"), className="btn primary"),
    ], className="btn-row", style={"alignItems": "center"})
    upload = dcc.Upload(id={"type": "upload", "name": "rpt"}, children=html.Span("Upload template"), className="btn small",
                        style={"display": "inline-flex"})
    report = None
    share_card = None
    if rep:
        f = json.loads(rep["findings"])
        unver = f.get("narrative_unverified") or []
        report = _section("Latest report", [
            html.Div([html.Span(f"#{rep['id']} · {rep['template'].replace('.md.j2', '').replace('_', ' ')} · {_ts(rep['ts'])} · {who(rep['actor'])}",
                                className="muted small"),
                      tip(f"Findings hash {rep['findings_hash']} · narrative: {rep['narrative_source']}"),
                      html.Div([html.A(".docx", href=f"/files/report/{rep['id']}/docx", className="btn small"),
                                html.A("PDF / HTML", href=f"/files/report/{rep['id']}/html", target="_blank", className="btn small"),
                                html.A("Markdown", href=f"/files/report/{rep['id']}/md", className="btn small"),
                                html.Button("Google Docs", id=act("gdoc"), className="btn small") if google.enabled() else None],
                               className="btn-row", style={"marginLeft": "auto"})], className="chips", style={"marginBottom": "10px"}),
            html.Div(f"Check these figures, not found in the engine output: {', '.join(unver)}", className="notice bad") if unver else None,
            html.Iframe(srcDoc=open(rep["html_path"]).read(), className="report-frame"),
        ])
        from valor.share import report_link
        link = report_link(rep)
        subject = f"{settings()['share']['subject_prefix']} {case['borrower_name']}: {t['name'].lower()} valuation review ({case['status']})"
        op = case["opinion"]
        body = (f"Hello,\n\nThe second-line valuation review for {case['borrower_name']} ({case['id']}) is {case['status']}.\n\n"
                + (f"Opinion: {op['verdict_label']}. {op['rationale']}\n\n" if op else "")
                + f"{f['summary_line']}\n\nReport: {link}\n\nRegards,")
        share_card = _section("Share", [
            html.Div([html.Div([html.Label("To"), dcc.Input(id="mail-to", className="inp", value="")], className="field"),
                      html.Div([html.Label("Cc"), dcc.Input(id="mail-cc", className="inp", value=", ".join(settings()["share"]["default_cc"]))],
                               className="field")], className="grid-2"),
            html.Div([html.Label("Subject"), dcc.Input(id="mail-subject", className="inp", value=subject)], className="field"),
            html.Div([html.Label("Body"), dcc.Textarea(id="mail-body", className="inp", value=body, style={"minHeight": "180px"})], className="field"),
            html.Div(id="mail-note", className="small muted"),
            html.Div([html.A("Open in Gmail", id="mail-open", href="#", target="_blank", className="btn primary"),
                      html.Button("Redraft with agent", id=act("mail-draft"), className="btn"),
                      html.Button("Gmail draft (Apps Script)", id=act("mail-gs"), className="btn") if google.enabled() else None],
                     className="btn-row"),
        ], tip_text="Opens a prefilled Gmail compose window; you edit and send. Valor never sends. Links cannot carry attachments, "
                    "so the email links to the report in Google Drive.")
    return html.Div([step_head("Deliver", [badge(f"{ctx['n_reports']} report(s)")]),
                     _section("Generate a report", [gen], right=upload,
                              tip_text="Findings are built once from the engine and rendered into any template: same numbers, any format."),
                     report or empty_state("No report yet: choose a template and generate"),
                     share_card])


# ── audit ────────────────────────────────────────────────────────────

EVENT_LABEL = {"case_created": "Case created", "data_pulled": "Data pulled", "input_adjusted": "Input adjusted",
               "recommendation_applied": "Input adjusted (agent rec.)", "valuation_run": "Valuation run",
               "agent_explained": "Agent explained", "recommendation_made": "Agent recommended",
               "agent_recommendations_requested": "Recommendations requested", "recommendation_accepted": "Rec. accepted",
               "recommendation_edited": "Rec. edited", "recommendation_rejected": "Rec. rejected", "submitted": "Submitted",
               "sent_back": "Sent back", "approved": "Approved", "locked": "Locked", "report_generated": "Report generated",
               "email_drafted": "Email drafted", "email_compose_opened": "Gmail opened", "gmail_draft_created": "Gmail draft created",
               "report_exported": "Exported to Google Docs", "opinion_set": "Opinion recorded",
               "agent_opinion_drafted": "Agent drafted opinion", "template_uploaded": "Template uploaded",
               "challenge_raised": "Reviewer challenge", "challenge_applied": "Input adjusted (challenge)",
               "challenge_accepted": "Challenge accepted", "challenge_declined": "Challenge declined", "data_exported": "Data exported"}
EVENT_GROUP = {"challenge_raised": "workflow", "challenge_applied": "input", "input_adjusted": "input", "recommendation_applied": "input", "data_pulled": "input", "valuation_run": "run",
               "agent_explained": "agent", "recommendation_made": "agent", "agent_recommendations_requested": "agent",
               "agent_opinion_drafted": "agent", "email_drafted": "agent"}


def _audit(case, t, uid, ctx):
    trail = store.audit_trail(case["id"])
    chain = store.verify_chain()
    items = []
    for e in reversed(trail):
        det = json.loads(e["details"]) if e["details"] else {}
        unit = det.get("unit", "musd")

        def f(v, unit=unit):
            try:
                return fmt(float(v), unit)
            except (TypeError, ValueError):
                return v or "—"
        change = None
        if e["field"] and (e["old_value"] is not None or e["new_value"] is not None):
            change = html.Div([html.Span(e["label"] or e["field"]), ": ", f(e["old_value"]), " → ", html.B(f(e["new_value"]))], className="audit-change")
        elif e["event"] == "opinion_set":
            change = html.Div(html.B(e["new_value"]), className="audit-change")
        elif e["event"] == "valuation_run":
            change = html.Div(f"Run #{det.get('run_id')}: {money(det.get('low'))} / {money(det.get('mid'))} / {money(det.get('high'))}"
                              + (f" · {det.get('rag')}" if det.get("rag") else ""), className="audit-change")
        elif e["event"] in ("recommendation_made", "recommendation_accepted", "recommendation_edited", "recommendation_rejected"):
            change = html.Div(det.get("title", ""), className="small")
        group = EVENT_GROUP.get(e["event"], "workflow")
        items.append(html.Div([
            html.Div([_ts(e["ts"]), tip(f"#{e['id']} · {e['hash'][:16]}")], className="audit-time"),
            html.Div(who(e["actor"]), className=f"audit-who {'agent' if e['actor'].startswith('agent:') else ''}"),
            html.Div([html.Span(EVENT_LABEL.get(e["event"], e["event"]), className="audit-event"), change,
                      html.Div(f"“{e['rationale']}”", className="audit-why small") if e["rationale"] else None]),
        ], className="audit-item", **{"data-group": group}))
    filters = html.Div([html.Button("All", className="chip on", **{"data-filter": "all"})] +
                       [html.Button(lab, className="chip", **{"data-filter": g}) for g, lab in
                        (("input", "Inputs"), ("run", "Runs"), ("agent", "Agent"), ("workflow", "Workflow"))],
                       className="chips", **{"data-filter-group": "audit"})
    return html.Div([
        step_head("Audit trail", [rag_chip("green" if chain["ok"] else "red", "Chain verified" if chain["ok"] else "Chain broken"),
                                  tip(f"Append-only, hash-chained log: {chain['entries']} entries across all cases"
                                      + (f", head {chain.get('head')}." if chain["ok"] else f"; first bad entry #{chain.get('broken_at')}."))],
                  html.A("Export CSV", href=f"/files/audit/{case['id']}.csv", className="btn small")),
        filters, html.Div(style={"height": "12px"}),
        html.Div(items, className="panel", style={"paddingTop": "8px"}, **{"data-filter-target": "audit"}),
    ])
