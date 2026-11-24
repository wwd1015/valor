"""Valor Dash app: shell, routing and callbacks. Run with `python -m valor` (or `python app.py`)."""

from __future__ import annotations

import base64
import csv
import io
import time
from pathlib import Path

from dash import ALL, Dash, Input, Output, State, ctx, dcc, html, no_update
from flask import Response, abort, send_file

from valor import service, share, store
from valor.agent import runner
from valor.config import settings, user, users
from valor.fmt import display_value, fmt, parse_input
from valor.report import findings as findings_mod
from valor.report import render as report_render
from valor.ui.pages import case as case_page
from valor.ui.pages import cases as cases_page
from valor.ui.pages import engine as engine_page

FONTS = ("https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght,SOFT,WONK@0,9..144,300..700,0..100,0..1;"
         "1,9..144,300..700,0..100,0..1&family=Hanken+Grotesk:wght@400..700&display=swap")

app = Dash(__name__, title="Valor", suppress_callback_exceptions=True, update_title=None,
           assets_folder=str(Path(__file__).parent / "assets"), external_stylesheets=[FONTS])
app.index_string = app.index_string.replace("<html>", '<html lang="en" data-theme="light">')
server = app.server
LAST_PARITY: dict = {}


def _masthead():
    cfg = settings()["app"]
    mode = runner.mode()
    return html.Header(html.Div([
        dcc.Link([html.Div("V", className="brand-mark"),
                  html.Div([html.Div(cfg["title"], className="brand-name"), html.Div(cfg["subtitle"], className="eyebrow")])],
                 href="/", className="brand"),
        html.Div([
            dcc.Link("Cases", href="/", className="masthead-link"),
            dcc.Link("New case", href="/new", className="masthead-link"),
            dcc.Link("Engine", href="/engine", className="masthead-link"),
            html.Span(f"agent: {mode}", className=f"mode-chip {mode}",
                      title="claude = Claude Code headless (claude -p); mock = deterministic rules"),
            html.Div([html.Span("Acting as", className="eyebrow"),
                      dcc.Dropdown(id="user", clearable=False, searchable=False, persistence=True, persistence_type="local",
                                   value=users()[0]["id"], style={"width": "250px"},
                                   options=[{"label": f"{u['name']} · {u['role']}", "value": u["id"]} for u in users()])],
                     className="user-pick"),
        ], className="masthead-tools"),
    ], className="masthead-row"), className="masthead")


def _modal(prefix: str, title_id: str, body: list) -> html.Div:
    return html.Div(html.Div([html.Div(html.H2(id=title_id, className="modal-title"), className="modal-head"),
                              html.Div(body, className="modal-body")], className="modal", role="dialog"),
                    id=f"{prefix}-modal", className="modal-backdrop hidden")


app.layout = html.Div([
    dcc.Location(id="url"),
    dcc.Store(id="tick", data=0),
    dcc.Store(id="adj-key"),
    dcc.Store(id="rec-target"),
    dcc.Store(id="whatif", data={}, storage_type="session"),
    html.Div([html.Span("Demonstration only", className="eyebrow"),
              html.Span("Mock data. Not a credit decision. Templates, thresholds and roles are illustrative.")],
             className="demo-banner", role="note"),
    _masthead(),
    html.Main(html.Div(id="page"), className="page"),
    html.Div(id="toast"),
    dcc.Loading(html.Div(id="busy"), delay_show=250, className="busy-wrap",
                custom_spinner=html.Div(html.Div([html.Span(className="busy-dot"), "Working… agent calls can take up to a minute."],
                                                 className="busy-card"), className="busy-overlay")),
    _modal("adj", "adj-title", [
        html.Div(id="adj-context", className="small muted"),
        html.Div([html.Label("New value", htmlFor="adj-value"), dcc.Input(id="adj-value", className="inp", debounce=False),
                  html.Div(id="adj-unit", className="help")], className="field"),
        html.Div([html.Label("Rationale (required)", htmlFor="adj-rationale"),
                  dcc.Textarea(id="adj-rationale", className="inp", placeholder="Why this value? This goes to the audit trail and the report.")],
                 className="field"),
        html.Div([html.Button("Save change", id="adj-save", className="btn primary"),
                  html.Button("Reset to source", id="adj-reset", className="btn"),
                  html.Button("Cancel", id="adj-cancel", className="btn link")], className="btn-row"),
    ]),
    _modal("rec", "rec-title", [
        html.Div(id="rec-context", className="small muted"),
        html.Div([html.Label("Value to apply"), dcc.Input(id="rec-value", className="inp")], className="field", id="rec-value-wrap"),
        html.Div([html.Label("Note (required)"), dcc.Textarea(id="rec-note", className="inp")], className="field"),
        html.Div([html.Button("Confirm", id="rec-confirm", className="btn primary"),
                  html.Button("Cancel", id="rec-cancel", className="btn link")], className="btn-row"),
    ]),
    html.Footer(html.Div([html.Span(f"{settings()['app']['institution']} · prototype · all data is mock"),
                          html.Span("Numbers come from the deterministic engine; Claude advises.")], className="page-foot"),
                className="page"),
])


def toast(msg: str, kind: str = "ok"):
    return html.Div(msg, className=f"toast {kind}", key=str(time.time()))


def _case_id(path: str | None) -> str | None:
    parts = (path or "").strip("/").split("/")
    return parts[1] if len(parts) >= 2 and parts[0] == "case" else None


# ── routing ──────────────────────────────────────────────────────────

@app.callback(Output("page", "children"), Input("url", "pathname"), Input("tick", "data"), Input("user", "value"))
def route(path, _tick, uid):
    parts = (path or "/").strip("/").split("/")
    try:
        if parts[0] == "case" and len(parts) >= 2:
            return case_page.render(parts[1], parts[2] if len(parts) > 2 else "intake", uid)
        if parts[0] == "new":
            return cases_page.render_new(uid)
        if parts[0] == "engine":
            return engine_page.render(uid, LAST_PARITY.get("rows"))
        return cases_page.render(uid)
    except Exception as e:  # noqa: BLE001 - show, don't crash the page
        return html.Div(f"Error rendering page: {e}", className="notice bad")


# ── new case ─────────────────────────────────────────────────────────

@app.callback(Output("new-deal-facts", "children"), Output("new-workflow", "value"), Input("new-deal", "value"),
              prevent_initial_call=True)
def new_deal(deal_id):
    from valor.data import get_source
    from valor.workflow import suggest_workflow
    if not deal_id:
        return None, no_update
    return cases_page.deal_facts(deal_id), suggest_workflow(get_source().deal(deal_id)["risk_status"])


@app.callback(Output("new-workflow-preview", "children"), Input("new-workflow", "value"))
def new_preview(wid):
    return cases_page.workflow_preview(wid) if wid else None


@app.callback(Output("url", "pathname", allow_duplicate=True), Output("toast", "children", allow_duplicate=True),
              Input("new-create", "n_clicks"), State("new-deal", "value"), State("new-workflow", "value"), State("user", "value"),
              prevent_initial_call=True)
def new_create(n, deal_id, wid, uid):
    if not n:
        return no_update, no_update
    if not deal_id:
        return no_update, toast("Choose a deal first.", "error")
    cid = service.create_case(deal_id, wid, uid)
    return f"/case/{cid}/scope", toast(f"Case {cid} created.")


# ── action dispatcher (all simple buttons) ───────────────────────────

@app.callback(Output("tick", "data", allow_duplicate=True), Output("toast", "children", allow_duplicate=True),
              Output("busy", "children", allow_duplicate=True),
              Input({"type": "act", "name": ALL}, "n_clicks"),
              State({"type": "field", "name": ALL}, "value"), State({"type": "field", "name": ALL}, "id"),
              State("url", "pathname"), State("user", "value"), State("tick", "data"), prevent_initial_call=True)
def dispatch(_clicks, field_values, field_ids, path, uid, tick):
    trig = ctx.triggered_id
    if not trig or not ctx.triggered[0]["value"]:
        return no_update, no_update, no_update
    name = trig["name"]
    fields = {i["name"]: v for i, v in zip(field_ids, field_values)}
    cid = _case_id(path)
    try:
        if name == "pull":
            r = service.pull_data(cid, uid)
            msg = f"Pulled {r['inputs']} inputs from the data source." + (f" {r['changed']} source value(s) changed." if r["changed"] else "")
        elif name == "run":
            run = service.run_valuation(cid, uid)
            c = run["results"]["conclusion"]
            msg = f"Valuation run #{run['id']}: midpoint {fmt(c['mid'])} (USD m), {len(run['checks'])} check(s)."
        elif name == "explain":
            service.explain(cid, uid)
            msg = "Commentary written."
        elif name == "recs":
            n = service.generate_recommendations(cid, uid)
            msg = f"The agent made {n} recommendation(s)."
        elif name == "submit":
            service.submit(cid, uid, fields.get("review-comment") or "")
            msg = "Submitted for review."
        elif name == "approve":
            service.approve(cid, uid, fields.get("review-comment") or "")
            msg = "Approved. The case is locked."
        elif name == "sendback":
            service.send_back(cid, uid, fields.get("review-comment") or "")
            msg = "Sent back to the analyst."
        elif name == "opinion-draft":
            d = service.draft_opinion(cid, uid)
            msg = f"Agent drafted an opinion ({d['source']}). Edit it, then save."
        elif name == "opinion-save":
            case = service.get_case(cid)
            draft = case["extras"].get("opinion_draft") or {}
            prev = case["opinion"] or {}
            conds = [c for c in (fields.get("op-conditions") or "").splitlines() if c.strip()]
            op = service.set_opinion(cid, uid, fields.get("op-verdict"), fields.get("op-rationale") or "", conds,
                                     risks=prev.get("risks") or draft.get("risks") or [],
                                     questions=prev.get("questions") or draft.get("questions") or [],
                                     source="analyst" + (" (agent draft)" if draft else ""))
            msg = f"Opinion recorded: {op['verdict_label']}."
        elif name == "report":
            r = report_render.generate(cid, fields.get("rpt-template"), uid, use_agent="agent" in (fields.get("rpt-agent") or []))
            msg = f"Report #{r['id']} generated ({r['template']['name']})."
        elif name == "gdoc":
            url = report_render.export_google(cid, uid)
            msg = f"Exported to Google Docs: {url}"
        elif name == "parity":
            from valor.config import engine_registry
            from valor.excel import workbook
            LAST_PARITY["rows"] = [workbook.parity(m) for m in engine_registry()]
            ok = sum(1 for p in LAST_PARITY["rows"] if p["ok"])
            msg = f"Parity: {ok} of {len(LAST_PARITY['rows'])} methods match the workbook."
        else:
            return no_update, no_update, no_update
        return (tick or 0) + 1, toast(msg), ""
    except service.ReviewError as e:
        return no_update, toast(str(e), "error"), ""
    except Exception as e:  # noqa: BLE001
        return no_update, toast(f"{type(e).__name__}: {e}", "error"), ""


# ── input adjustment modal ───────────────────────────────────────────

@app.callback(Output("adj-key", "data"), Output("adj-modal", "className"), Output("adj-title", "children"),
              Output("adj-context", "children"), Output("adj-value", "value"), Output("adj-unit", "children"),
              Output("adj-rationale", "value"),
              Input({"type": "adj-open", "key": ALL}, "n_clicks"), State("url", "pathname"), prevent_initial_call=True)
def adj_open(_n, path):
    trig = ctx.triggered_id
    if not trig or not ctx.triggered[0]["value"]:
        return (no_update,) * 7
    row = store.one("SELECT * FROM case_inputs WHERE case_id = ? AND key = ?", (_case_id(path), trig["key"]))
    unit_help = {"pct": "Percent, e.g. 7.5 for 7.5%", "x": "Multiple, e.g. 8.5", "musd": "USD millions", "num": "Number"}[row["unit"]]
    context = [html.Div(["Source: ", html.Span(row["source_ref"], className="src")]),
               html.Div(f"Source value {fmt(row['source_value'], row['unit'])} · current {fmt(row['value'], row['unit'])}")]
    return trig["key"], "modal-backdrop", f"Adjust: {row['label']}", context, display_value(row["value"], row["unit"]), unit_help, ""


@app.callback(Output("adj-modal", "className", allow_duplicate=True), Output("tick", "data", allow_duplicate=True),
              Output("toast", "children", allow_duplicate=True),
              Input("adj-save", "n_clicks"), Input("adj-reset", "n_clicks"), Input("adj-cancel", "n_clicks"),
              State("adj-key", "data"), State("adj-value", "value"), State("adj-rationale", "value"),
              State("url", "pathname"), State("user", "value"), State("tick", "data"), prevent_initial_call=True)
def adj_save(_s, _r, _c, key, value, rationale, path, uid, tick):
    if ctx.triggered_id == "adj-cancel":
        return "modal-backdrop hidden", no_update, no_update
    cid = _case_id(path)
    row = store.one("SELECT * FROM case_inputs WHERE case_id = ? AND key = ?", (cid, key))
    try:
        if ctx.triggered_id == "adj-reset":
            new = row["source_value"]
        else:
            try:
                new = parse_input(value, row["unit"])
            except (TypeError, ValueError):
                return no_update, no_update, toast("Enter a number.", "error")
        service.adjust_input(cid, key, new, rationale, uid)
    except service.ReviewError as e:
        return no_update, no_update, toast(str(e), "error")
    return "modal-backdrop hidden", (tick or 0) + 1, toast(f"{row['label']}: {fmt(row['value'], row['unit'])} → {fmt(new, row['unit'])}. Re-run the valuation to update results.")


# ── recommendation decisions ─────────────────────────────────────────

@app.callback(Output("rec-target", "data"), Output("rec-modal", "className"), Output("rec-title", "children"),
              Output("rec-context", "children"), Output("rec-value", "value"), Output("rec-value-wrap", "className"),
              Output("rec-note", "value"), Output("tick", "data", allow_duplicate=True), Output("toast", "children", allow_duplicate=True),
              Input({"type": "rec-accept", "id": ALL}, "n_clicks"), Input({"type": "rec-edit", "id": ALL}, "n_clicks"),
              Input({"type": "rec-reject", "id": ALL}, "n_clicks"), State("user", "value"), State("tick", "data"),
              prevent_initial_call=True)
def rec_click(_a, _e, _r, uid, tick):
    trig = ctx.triggered_id
    if not trig or not ctx.triggered[0]["value"]:
        return (no_update,) * 9
    rec = store.one("SELECT * FROM recommendations WHERE id = ?", (trig["id"],))
    if trig["type"] == "rec-accept":
        try:
            service.decide_recommendation(rec["id"], "accept", uid)
        except service.ReviewError as e:
            return (no_update,) * 8 + (toast(str(e), "error"),)
        return (no_update,) * 7 + ((tick or 0) + 1, toast(f"Accepted: {rec['title']}" + (". Re-run the valuation." if rec["field"] else ".")))
    unit = "musd"
    if rec["field"]:
        unit = store.one("SELECT unit FROM case_inputs WHERE case_id = ? AND key = ?", (rec["case_id"], rec["field"]))["unit"]
    mode = "edit" if trig["type"] == "rec-edit" else "reject"
    title = ("Edit and apply: " if mode == "edit" else "Reject: ") + rec["title"]
    value = display_value(rec["proposed_value"], unit) if rec["proposed_value"] is not None else ""
    return ({"id": rec["id"], "mode": mode, "unit": unit}, "modal-backdrop", title, rec["rationale"], value,
            "field" if mode == "edit" else "field hidden", "", no_update, no_update)


@app.callback(Output("rec-modal", "className", allow_duplicate=True), Output("tick", "data", allow_duplicate=True),
              Output("toast", "children", allow_duplicate=True),
              Input("rec-confirm", "n_clicks"), Input("rec-cancel", "n_clicks"), State("rec-target", "data"),
              State("rec-value", "value"), State("rec-note", "value"), State("user", "value"), State("tick", "data"),
              prevent_initial_call=True)
def rec_confirm(_c, _x, target, value, note, uid, tick):
    if ctx.triggered_id == "rec-cancel" or not target:
        return "modal-backdrop hidden", no_update, no_update
    try:
        v = parse_input(value, target["unit"]) if target["mode"] == "edit" else None
        service.decide_recommendation(target["id"], target["mode"], uid, value=v, note=note)
    except (TypeError, ValueError):
        return no_update, no_update, toast("Enter a number.", "error")
    except service.ReviewError as e:
        return no_update, no_update, toast(str(e), "error")
    return "modal-backdrop hidden", (tick or 0) + 1, toast("Recorded." + (" Re-run the valuation." if target["mode"] == "edit" else ""))


@app.callback(Output("tick", "data", allow_duplicate=True), Input("explain-poll", "n_intervals"),
              State("url", "pathname"), State("tick", "data"), prevent_initial_call=True)
def explain_poll(_n, path, tick):
    run = service.latest_run(_case_id(path) or "")
    if run and (run.get("explanation") or not service.explanation_pending(run["id"])):
        return (tick or 0) + 1                      # re-render: the commentary is in (or generation stopped)
    return no_update


# ── what-if sandbox and reviewer challenges ──────────────────────────

@app.callback(Output("whatif-list", "children"), Output("whatif-result", "children"),
              Input("whatif", "data"), Input("whatif-mount", "data"))
def whatif_show(store_data, case_id):
    if not case_id:
        return no_update, no_update
    return case_page.whatif_result(case_id, (store_data or {}).get(case_id, {}))


@app.callback(Output("whatif-value", "value"), Output("whatif-unit", "children"), Input("whatif-key", "value"),
              State("whatif-mount", "data"), prevent_initial_call=True)
def whatif_pick(key, case_id):
    if not key:
        return no_update, ""
    row = store.one("SELECT * FROM case_inputs WHERE case_id = ? AND key = ?", (case_id, key))
    hint = {"pct": "Percent, e.g. 7.5 for 7.5%", "x": "Multiple, e.g. 8.5", "musd": "USD millions", "num": "Number", "yrs": "Years"}
    return display_value(row["value"], row["unit"]), f"{hint.get(row['unit'], '')} · source {fmt(row['source_value'], row['unit'])}"


@app.callback(Output("whatif", "data", allow_duplicate=True), Output("toast", "children", allow_duplicate=True),
              Input("whatif-add", "n_clicks"), Input("whatif-clear", "n_clicks"), Input({"type": "whatif-rm", "key": ALL}, "n_clicks"),
              State("whatif-key", "value"), State("whatif-value", "value"), State("whatif", "data"), State("whatif-mount", "data"),
              prevent_initial_call=True)
def whatif_edit(_a, _c, _r, key, value, data, case_id):
    trig = ctx.triggered_id
    if not trig or not ctx.triggered[0]["value"]:
        return no_update, no_update
    data = dict(data or {})
    cur = dict(data.get(case_id, {}))
    if trig == "whatif-clear":
        cur = {}
    elif isinstance(trig, dict):
        cur.pop(trig["key"], None)
    else:
        if not key:
            return no_update, toast("Choose an assumption.", "error")
        row = store.one("SELECT unit FROM case_inputs WHERE case_id = ? AND key = ?", (case_id, key))
        try:
            cur[key] = parse_input(value, row["unit"])
        except (TypeError, ValueError):
            return no_update, toast("Enter a number.", "error")
    data[case_id] = cur
    return data, no_update


@app.callback(Output("whatif", "data", allow_duplicate=True), Output("tick", "data", allow_duplicate=True),
              Output("toast", "children", allow_duplicate=True), Output("url", "pathname", allow_duplicate=True),
              Input("whatif-sendback", "n_clicks"), State("whatif-comment", "value"), State("whatif", "data"),
              State("whatif-mount", "data"), State("user", "value"), State("tick", "data"), prevent_initial_call=True)
def whatif_sendback(n, comment, data, case_id, uid, tick):
    if not n:
        return no_update, no_update, no_update, no_update
    try:
        k = service.send_back_with_challenges(case_id, uid, (data or {}).get(case_id, {}), comment or "")
    except service.ReviewError as e:
        return no_update, no_update, toast(str(e), "error"), no_update
    data = dict(data or {})
    data.pop(case_id, None)
    return data, (tick or 0) + 1, toast(f"Sent back with {k} challenge(s)."), f"/case/{case_id}/approval"


@app.callback(Output("tick", "data", allow_duplicate=True), Output("toast", "children", allow_duplicate=True),
              Input({"type": "chal-accept", "id": ALL}, "n_clicks"), Input({"type": "chal-decline", "id": ALL}, "n_clicks"),
              State({"type": "chal-note", "id": ALL}, "value"), State({"type": "chal-note", "id": ALL}, "id"),
              State("user", "value"), State("tick", "data"), prevent_initial_call=True)
def challenge_resolve(_a, _d, notes, note_ids, uid, tick):
    trig = ctx.triggered_id
    if not trig or not ctx.triggered[0]["value"]:
        return no_update, no_update
    note = {i["id"]: v for i, v in zip(note_ids, notes)}.get(trig["id"], "")
    try:
        service.resolve_challenge(trig["id"], "accept" if trig["type"] == "chal-accept" else "decline", uid, note or "")
    except service.ReviewError as e:
        return no_update, toast(str(e), "error")
    return (tick or 0) + 1, toast("Challenge answered." + (" Re-run the valuation." if trig["type"] == "chal-accept" else ""))


# ── report template upload ───────────────────────────────────────────

@app.callback(Output("tick", "data", allow_duplicate=True), Output("toast", "children", allow_duplicate=True),
              Input({"type": "upload", "name": "rpt"}, "contents"), State({"type": "upload", "name": "rpt"}, "filename"),
              State("url", "pathname"), State("user", "value"), State("tick", "data"), prevent_initial_call=True)
def upload_template(contents, filename, path, uid, tick):
    if not contents or not contents[0]:
        return no_update, no_update
    raw = base64.b64decode(contents[0].split(",", 1)[1])
    try:
        sample = findings_mod.build(_case_id(path), uid)
        sample.update(narrative={"executive_summary": "", "methodology_commentary": "", "key_judgements": "", "conclusion": ""},
                      narrative_source="none", narrative_unverified=[])
        meta = report_render.save_uploaded(filename[0], raw, sample)
    except service.ReviewError as e:
        return no_update, toast(str(e), "error")
    store.audit(_case_id(path), uid, "template_uploaded", details={"template": meta["id"]})
    return (tick or 0) + 1, toast(f"Template “{meta['name']}” added. Choose it from the list.")


# ── share ────────────────────────────────────────────────────────────

def _split(s):
    return [x.strip() for x in (s or "").replace(";", ",").split(",") if x.strip()]


@app.callback(Output("mail-open", "href"), Input("mail-to", "value"), Input("mail-cc", "value"),
              Input("mail-subject", "value"), Input("mail-body", "value"))
def mail_href(to, cc, subject, body):
    return share.gmail_compose_url(_split(to), _split(cc), subject or "", body or "")


@app.callback(Output("toast", "children", allow_duplicate=True), Input("mail-open", "n_clicks"),
              State("mail-to", "value"), State("mail-subject", "value"), State("url", "pathname"), State("user", "value"),
              prevent_initial_call=True)
def mail_opened(n, to, subject, path, uid):
    if not n:
        return no_update
    share.log_open(_case_id(path), uid, _split(to), subject)
    return toast("Opened in Gmail. Review and send it yourself; Valor never sends.")


@app.callback(Output("mail-subject", "value"), Output("mail-body", "value"), Output("mail-note", "children"),
              Output("busy", "children", allow_duplicate=True),
              Input({"type": "act", "name": "mail-draft"}, "n_clicks"), State("url", "pathname"), State("user", "value"),
              prevent_initial_call=True)
def mail_draft(n, path, uid):
    if not n:
        return no_update, no_update, no_update, no_update
    try:
        d = share.draft(_case_id(path), uid)
    except service.ReviewError as e:
        return no_update, no_update, str(e), ""
    note = f"Drafted by the agent ({d['source']})."
    if d["unverified"]:
        note += f" Check these figures, not found in the engine output: {', '.join(d['unverified'])}."
    return d["subject"], d["body"], note, ""


@app.callback(Output("toast", "children", allow_duplicate=True), Input({"type": "act", "name": "mail-gs"}, "n_clicks"),
              State("mail-to", "value"), State("mail-cc", "value"), State("mail-subject", "value"), State("mail-body", "value"),
              State("url", "pathname"), State("user", "value"), prevent_initial_call=True)
def mail_gs(n, to, cc, subject, body, path, uid):
    if not n:
        return no_update
    try:
        r = share.apps_script_draft(_case_id(path), uid, _split(to), _split(cc), subject, body)
    except Exception as e:  # noqa: BLE001
        return toast(str(e), "error")
    return toast(f"Gmail draft created: {r.get('url', '')}")


# ── files ────────────────────────────────────────────────────────────

@server.route("/files/report/<int:rid>/<kind>")
def report_file(rid: int, kind: str):
    rep = store.one("SELECT * FROM reports WHERE id = ?", (rid,))
    if not rep or kind not in ("html", "docx", "md"):
        abort(404)
    path = rep[f"{kind}_path"]
    return send_file(path, as_attachment=kind != "html", download_name=Path(path).name)


@server.route("/files/data/<case_id>.xlsx")
def data_xlsx(case_id: str):
    import pandas as pd
    tables = service.pulled_tables(case_id)
    if not tables:
        abort(404)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        inputs = pd.DataFrame(service.get_inputs(case_id))[["grp", "label", "unit", "source_value", "value", "source_ref"]]
        inputs.columns = ["group", "input", "unit", "source value", "value used", "source"]
        inputs.to_excel(xw, sheet_name="Inputs", index=False)
        for name, df in tables.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
    store.audit(case_id, "system", "data_exported", details={"format": "xlsx", "tables": list(tables)})
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"{case_id}_data.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@server.route("/files/data/<case_id>/<name>.csv")
def data_csv(case_id: str, name: str):
    df = service.pulled_tables(case_id).get(name)
    if df is None:
        abort(404)
    return Response(df.to_csv(index=False), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={case_id}_{name}.csv"})


@server.route("/files/audit/<case_id>.csv")
def audit_csv(case_id: str):
    rows = store.audit_trail(case_id)
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            r = dict(r)
            r["actor_name"] = user(r["actor"])["name"] if not r["actor"].startswith("agent:") else r["actor"]
            w.writerow({k: r[k] for k in rows[0].keys()})
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={case_id}_audit.csv"})


def main() -> None:
    import os
    port = int(os.environ.get("VALOR_PORT", "8050"))
    app.run(debug=os.environ.get("VALOR_DEBUG") == "1", port=port, host="127.0.0.1")


if __name__ == "__main__":
    main()
