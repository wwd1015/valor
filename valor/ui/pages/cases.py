"""Case list as a grid of expanding cards, and new-case intake."""

from __future__ import annotations

from dash import dcc, html

from valor import service
from valor.config import engine_registry, settings
from valor.data import get_source
from valor.engine.review import rag
from valor.fmt import money, pct
from valor.ui.components import empty_state, expandable, kv_table, rag_chip, section, status_badge, verdict_chip, who
from valor.workflow import suggest_workflow, templates

GROUPS = [("action", "Needs action"), ("review", "In review"), ("approved", "Approved")]


def _group(status: str) -> str:
    return {"draft": "action", "returned": "action", "submitted": "review", "approved": "approved"}[status]


def _next_step(c: dict, run: dict | None, open_recs: int) -> str:
    if c["status"] == "approved":
        return "Locked"
    if c["status"] == "submitted":
        return "Awaiting checker"
    if c["status"] == "returned":
        return "Sent back to analyst"
    if not c["data_pulled_at"]:
        return "Pull data"
    if not run:
        return "Run valuation"
    if open_recs:
        return f"{open_recs} open recommendation(s)"
    if not c.get("opinion"):
        return "Record opinion"
    return "Submit for review"


def case_card(c: dict) -> tuple:
    """A case as a card; clicking it grows into a centred sheet with the case's details. Returns (card, sheet)."""
    import json
    run = service.latest_run(c["id"])
    res = run["results"] if run else None
    concl = res["conclusion"] if res else None
    opinion = json.loads(c["opinion"]) if c.get("opinion") else None
    deal = json.loads(c["deal"]) if c.get("deal") else {}
    troubled = c["workflow"] == "troubled"
    t = templates()[c["workflow"]]
    open_recs = sum(1 for r in service.recommendations(c["id"]) if r["status"] == "open")
    open_ch = sum(1 for x in service.challenges(c["id"]) if x["status"] == "open")
    vs = concl.get("vs_first_line") if concl else None
    status = rag(vs, settings()["policy"]) if concl else "grey"
    href = f"/case/{c['id']}"
    measure = "Recovery" if troubled else "Enterprise value"

    front = [
        html.Div([html.Div(c["borrower_name"], className="card-name"), status_badge(c["status"])], className="card-top"),
        html.Div(money(concl["mid"]) if concl else "—", className="card-value"),
        html.Div(f"{measure} · USD m", className="card-unit"),
        html.Div([rag_chip(status, f"{pct(vs, signed=True)} vs 1st line" if vs is not None else "No valuation yet"),
                  verdict_chip(opinion["verdict"]) if opinion else None], className="card-chips"),
        html.Div(f"{c['id']} · {t['name']}", className="card-foot"),
    ]

    # sheet: the numbers, the deal, where it stands
    def tile(label, value, sub=None, cls="card"):
        return html.Div([html.Div(label, className="mini-label"), html.Div(value, className="big"),
                         html.Div(sub, className="card-metric") if sub else None], className=cls)
    tiles = [tile("Exposure", money(deal.get("commitment_musd")), f"{money(deal.get('outstanding_musd'))} drawn"),
             tile("First line", money(deal.get("first_line_value_musd")), deal.get("first_line_method"), "card accent")]
    if concl:
        tiles.append(tile("Second line", money(concl["mid"]), f"{money(concl['low'])} – {money(concl['high'])}"))
        if troubled:
            rv = res.get("reserve") or {}
            tiles.append(tile("Specific reserve", money(rv.get("reserve_mid")), f"{pct(rv.get('reserve_pct_mid'))} of exposure", "card fail"))
        else:
            tiles.append(tile("Loan-to-value", pct(concl.get("ltv_mid")), f"coverage {concl['coverage_mid']:.2f}x" if concl.get("coverage_mid") else None))
    facts = kv_table([("Sector", c["sector"]), ("Facility", f"{deal.get('facility_name', '')} · {deal.get('lien_position', '')}"),
                      ("Risk status", f"{deal.get('risk_status', '')} · rating {deal.get('internal_rating', '')}"),
                      ("Trigger", deal.get("request_type", "—")), ("Due", deal.get("review_due", "—")),
                      ("Analyst", who(c["created_by"])), ("Relationship manager", deal.get("relationship_manager", "—")),
                      ("Updated", c["updated_at"][:16].replace("T", " ") + " UTC")])
    state = [html.Div([html.Div("Next", className="mini-label"), html.Div(_next_step(c, run, open_recs), className="card-title")],
                      className="card accent")]
    if open_ch or open_recs or (run and run["checks"]):
        bits = [f"{len(run['checks'])} review check(s)" if run and run["checks"] else None,
                f"{open_recs} open recommendation(s)" if open_recs else None, f"{open_ch} open reviewer challenge(s)" if open_ch else None]
        state.append(html.Div(" · ".join(b for b in bits if b), className="muted small", style={"margin": "8px 0"}))
    if opinion:
        n_cond = len(opinion["conditions"])
        state.append(html.Div([
            html.Div([verdict_chip(opinion["verdict"]), html.Span(f"{n_cond} condition(s)" if n_cond else "", className="muted small")],
                     className="chips"),
            html.Div(opinion["rationale"], className="agent-voice clamp", style={"marginTop": "8px"}),
            html.Div([f"Opinion by {who(opinion['by'])} · ", dcc.Link("full opinion", href=f"{href}/opinion")], className="muted small"),
        ], style={"marginTop": "10px"}))
    body = [
        html.Div(tiles, className="cards"),
        html.Div([html.Div([html.Div("Deal", className="eyebrow", style={"marginBottom": "4px"}), facts]),
                  html.Div([html.Div("Where it stands", className="eyebrow", style={"marginBottom": "6px"}), *state])], className="grid-2"),
    ]
    actions = [dcc.Link("Open case →", href=href, className="btn primary small"), dcc.Link("Valuation", href=f"{href}/valuation", className="btn small"),
               dcc.Link("Audit trail", href=f"{href}/audit", className="btn small")]
    head_stats = [(measure, money(concl["mid"]) if concl else "—")]
    if vs is not None:
        head_stats.append(("vs 1st line", pct(vs, signed=True)))
    return expandable(f"sheet-case-{c['id']}", c["borrower_name"], f"{c['id']} · {t['name']} · {deal.get('request_type', '')}",
                      head_stats, body, front, f"card case-card {'troubled' if troubled else ''}", "Details",
                      attrs={"data-group": _group(c["status"])}, actions=actions)


def render(uid: str) -> html.Div:
    cases = service.list_cases()
    by_group = {g: [c for c in cases if _group(c["status"]) == g] for g, _ in GROUPS}
    variances = []
    for c in cases:
        r = service.latest_run(c["id"])
        if r and r["results"]["conclusion"].get("vs_first_line") is not None:
            variances.append(abs(r["results"]["conclusion"]["vs_first_line"]))
    chips = html.Div([html.Button(["All", html.Span(len(cases), className="n")], className="chip on", **{"data-filter": "all"})] +
                     [html.Button([label, html.Span(len(by_group[g]), className="n")], className="chip", **{"data-filter": g})
                      for g, label in GROUPS],
                     className="chips", **{"data-filter-group": "cases"})
    head = html.Div([
        html.Div([html.Div("Second-line valuation review", className="eyebrow"), html.H1("Cases", className="page-title")]),
        dcc.Link("New case", href="/new", className="btn primary")], className="page-head")
    bar = html.Div([chips, html.Div(["Avg |Δ| to 1st line",
                                     html.B(pct(sum(variances) / len(variances)) if variances else "—")], className="home-stat")],
                   className="home-bar")
    if not cases:
        return html.Div([head, empty_state("No cases yet", dcc.Link("New case", href="/new", className="btn primary"))])
    ordered = [c for g, _ in GROUPS for c in by_group[g]]          # needs action first
    pairs = [case_card(c) for c in ordered]
    return html.Div([head, bar, html.Div([card for card, _ in pairs], className="card-grid", **{"data-filter-target": "cases"}),
                     *[sheet for _, sheet in pairs]])


def render_new(uid: str) -> html.Div:
    deals = get_source().deals()
    opts = [{"label": f"{d.deal_id} · {d.borrower_name} · {d.request_type}", "value": d.deal_id} for d in deals.itertuples()]
    return html.Div([
        html.Div([html.Div([html.Div("Intake", className="eyebrow"), html.H1("New review", className="page-title")])],
                 className="page-head"),
        section("Deal", [
            dcc.Dropdown(id="new-deal", options=opts, placeholder="Choose the valuation request…", clearable=False),
            html.Div(id="new-deal-facts", style={"marginTop": "14px"}),
        ], tip_text="Valuation requests from the deal pipeline (DEAL_FACILITY via the configured data source)."),
        section("Workflow", [
            dcc.RadioItems(id="new-workflow", className="choice",
                           options=[{"label": html.Span([html.Span(t["name"], className="choice-name"),
                                                         html.Div(t["tagline"], className="choice-tag")]), "value": t["id"]}
                                    for t in templates().values()], value="performing"),
            html.Div(id="new-workflow-preview", style={"marginTop": "14px"}),
        ], tip_text="Suggested from the deal's risk status; the workflow sets the inputs, methods and memo."),
        html.Div([html.Button("Create case", id="new-create", className="btn primary"),
                  dcc.Link("Cancel", href="/", className="btn link")], className="btn-row"),
    ])


def deal_facts(deal_id: str | None):
    if not deal_id:
        return None
    d = get_source().deal(deal_id)
    sw = suggest_workflow(d["risk_status"])
    return html.Div([
        html.Div([html.Div("Trigger", className="mini-label"), html.Div(d["request_type"], className="card-title")], className="card"),
        html.Div([html.Div("Exposure", className="mini-label"), html.Div(money(d["commitment_musd"]), className="big"),
                  html.Div(f"{money(d['outstanding_musd'])} drawn", className="card-metric")], className="card"),
        html.Div([html.Div("First line", className="mini-label"), html.Div(money(d["first_line_value_musd"]), className="big"),
                  html.Div(d["first_line_method"], className="card-metric")], className="card"),
        html.Div([html.Div("Status", className="mini-label"), html.Div(d["risk_status"], className="card-title"),
                  html.Div(["Suggested: ", html.B(templates()[sw]["name"])], className="card-metric")], className="card"),
    ], className="cards")


def workflow_preview(wid: str):
    t = templates()[wid]
    reg = engine_registry()
    return html.Div([
        html.Div([html.Div("Methods", className="mini-label"),
                  html.Div([html.Span(reg[m["id"]]["label"], className="badge", style={"marginRight": "4px"}) for m in t["methods"]],
                           style={"marginTop": "6px"})], className="card"),
        html.Div([html.Div("You get", className="mini-label"),
                  html.Ul([html.Li(x) for x in t["you_get"]], className="small", style={"paddingLeft": "18px", "margin": "6px 0 0"})],
                 className="card"),
    ], className="cards wide")
