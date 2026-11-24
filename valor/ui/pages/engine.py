"""Engine page: which module runs each method, its parity with the master workbook, and translation history."""

from __future__ import annotations

from dash import html

from valor.config import engine_registry
from valor.engine import method_module
from valor.excel import translate
from valor.ui.components import badge, expandable, kv_table, rag_chip, section, table, who


def render(uid: str, parity: list[dict] | None = None) -> html.Div:
    reg = engine_registry()
    pmap = {p["method"]: p for p in (parity or [])}
    cards, sheets = [], []
    for mid, spec in reg.items():
        mod = method_module(mid)
        p = pmap.get(mid)
        status = rag_chip("green", "Matches workbook") if p and p["ok"] else rag_chip("red", "Mismatch") if p else rag_chip("grey", "Not checked")
        rows = [{"o": r["output"].split(".")[1].capitalize(), "w": f"{r['workbook']:,.2f}", "e": f"{r['engine']:,.2f}",
                 "d": f"{r['diff']:+.4f}", "ok": "✓" if r["ok"] else "✗"} for r in (p or {}).get("rows", [])]
        body = [
            kv_table([("Module", html.Code(spec["module"])), ("Version", getattr(mod, "VERSION", "?")),
                      ("Workbook sheet", spec.get("workbook_sheet", "—"))]),
            html.Div("Engine vs workbook", className="eyebrow", style={"marginTop": "14px"}),
            table([("o", "Output", ""), ("w", "Workbook", "num"), ("e", "Engine", "num"), ("d", "Difference", "num"), ("ok", "", "")], rows)
            if rows else html.P("Not checked yet: use “Check parity” at the top of the page.", className="muted small"),
        ]
        card, sheet = expandable(f"sheet-eng-{mid}", spec["label"], "Method", [("Sheet", spec.get("workbook_sheet", "—"))], body,
                                 [html.Div(spec["label"], className="card-title"),
                                  html.Div(status, style={"margin": "10px 0 6px"}),
                                  html.Div(getattr(mod, "VERSION", "?").split(" ")[0], className="card-metric")],
                                 "card method-card", "Parity detail")
        cards.append(card)
        sheets.append(sheet)

    props = translate.proposals()
    prop_rows = [{"m": p["method"], "v": f"v{p['version']}",
                  "status": badge(p["status"], "good" if p["status"] in ("verified", "approved") else "bad" if p["status"] == "failed" else ""),
                  "agent": (p.get("agent") or {}).get("mode", ""), "when": p["created"][:16].replace("T", " "),
                  "sha": html.Span(p["sha256"][:12], className="src")} for p in props]
    reg_rows = [{"m": r["method"], "v": f"v{r['version']}", "mod": html.Code(r["module"]), "by": who(r["approved_by"]),
                 "when": r["approved_at"][:16].replace("T", " ")} for r in translate.registry()]
    howto_card, howto_sheet = expandable(
        "sheet-eng-howto", "Translate a method", "How it works", [],
        [html.Ol([html.Li("Claude reads the workbook sheet and proposes a Python module (a new version)."),
                  html.Li("The proposal is run on the workbook's own inputs; every output must match the workbook."),
                  html.Li("A named reviewer approves the verified version; it is copied into the engine and recorded."),
                  html.Li("Activating it points the method at the new module (config/engine.yaml).")], className="small"),
         html.Pre("python -m valor.excel propose --method dcf\n"
                  "python -m valor.excel verify  --method dcf --version 1\n"
                  "python -m valor.excel approve --method dcf --version 1 --reviewer m.reyes --activate", className="code")],
        [html.Div("Translate a method", className="card-title"),
         html.Div("Excel → Python, verified against the workbook, approved by a reviewer", className="card-metric")], "card accent", "Steps")

    return html.Div([
        html.Div([html.Div([html.Div("Deterministic engine", className="eyebrow"), html.H1("Valuation engine", className="page-title")]),
                  html.Button("Check parity against the workbook", id={"type": "act", "name": "parity"}, className="btn primary")],
                 className="page-head"),
        section("Methods", [html.Div(cards, className="cards", style={"marginBottom": "0"})],
                tip_text="Each method is a separate Python module translated from the master workbook. Parity re-runs it on the workbook's "
                         "inputs and compares with the workbook's own outputs. PLACEHOLDER: the workbook is a representative mock."),
        section("Translations", [
            html.Div([howto_card], className="cards"),
            html.Div("Proposals", className="eyebrow"),
            table([("m", "Method", ""), ("v", "Version", ""), ("status", "Status", ""), ("agent", "Proposed by", ""),
                   ("when", "Created (UTC)", ""), ("sha", "SHA-256", "")], prop_rows) if prop_rows else html.P("None yet.", className="muted small"),
            html.Div("Approved", className="eyebrow", style={"marginTop": "14px"}),
            table([("m", "Method", ""), ("v", "Version", ""), ("mod", "Module", ""), ("by", "Approved by", ""), ("when", "When (UTC)", "")],
                  reg_rows) if reg_rows else html.P("None yet.", className="muted small"),
        ], tip_text="Claude proposes; nothing runs until it reproduces the workbook and a reviewer approves it."),
        *sheets, howto_sheet,
    ])
