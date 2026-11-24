"""Plotly charts in the Ledger palette."""

from __future__ import annotations

import plotly.graph_objects as go

INK, INK2, LINE = "#1b2633", "#5b6776", "rgba(20,40,70,0.12)"
GREEN, BRASS, TEAL = "#004977", "#b08a2e", "#1a7bbf"
ACCENT = BRASS
FONT = dict(family="Hanken Grotesk, system-ui, sans-serif", size=12, color=INK)


def _layout(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(height=height, margin=dict(l=10, r=20, t=10, b=30), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", font=FONT, showlegend=False, hovermode="closest")
    fig.update_xaxes(gridcolor=LINE, zeroline=False, tickfont=dict(family="Hanken Grotesk, sans-serif", size=11, color=INK2))
    fig.update_yaxes(gridcolor="rgba(0,0,0,0)", tickfont=dict(size=12, color=INK), automargin=True)
    return fig


def football_field(methods: list[dict], conclusion: dict) -> go.Figure:
    """Ranges by method plus the reconciled range; first-line value and exposure as reference lines."""
    rows = [(m["label"], m["low"], m["mid"], m["high"], "#8aa3b8") for m in methods]
    rows.append(("Reconciled", conclusion["low"], conclusion["mid"], conclusion["high"], GREEN))
    rows = rows[::-1]
    fig = go.Figure()
    for label, lo, mid, hi, color in rows:
        fig.add_trace(go.Bar(y=[label], x=[hi - lo], base=[lo], orientation="h", marker=dict(color=color, opacity=0.95, cornerradius=3),
                             width=0.42, hovertemplate=f"{label}<br>low {lo:,.1f} · mid {mid:,.1f} · high {hi:,.1f}<extra></extra>"))
        fig.add_trace(go.Scatter(y=[label], x=[mid], mode="markers", marker=dict(symbol="line-ns", size=20, line=dict(width=2.5, color="#ffffff")),
                                 hoverinfo="skip"))
        fig.add_annotation(y=label, x=hi, text=f"{lo:,.0f} – {hi:,.0f}", showarrow=False, xanchor="left", xshift=8,
                           font=dict(family="Hanken Grotesk, sans-serif", size=11, color=INK2))
    refs = []
    if conclusion.get("first_line_value"):
        refs.append((conclusion["first_line_value"], "First line", ACCENT, "dash"))
    if conclusion["measure"] == "enterprise_value" and conclusion.get("bank_exposure"):
        refs.append((conclusion.get("debt_ahead", 0) + conclusion["bank_exposure"], "Debt through bank", INK2, "dot"))
    elif conclusion.get("bank_exposure"):
        refs.append((conclusion["bank_exposure"], "Bank exposure", INK2, "dot"))
    for x, name, color, dash in refs:
        fig.add_vline(x=x, line=dict(color=color, width=1.5, dash=dash))
        fig.add_annotation(x=x, y=1.02, yref="paper", text=f"{name} {x:,.0f}", showarrow=False, xanchor="center", yanchor="bottom",
                           font=dict(size=11, color=color))
    _layout(fig, 70 + 52 * len(rows))
    fig.update_layout(margin=dict(l=10, r=90, t=30, b=30), barmode="overlay")
    return fig


def waterfall_chart(method: dict) -> go.Figure:
    """Recovered vs claim amount by class, low and high scenario."""
    wf = method["details"]["waterfall"]
    claims = wf["low"]["claims"]
    labels = [f"P{c['priority']} {c['claim_class']}" + (" ◆" if c["bank_share"] > 0 else "") for c in claims][::-1]
    amt = [c["amount"] for c in claims][::-1]
    lo = [c["recovered"] for c in wf["low"]["claims"]][::-1]
    hi = [c["recovered"] for c in wf["high"]["claims"]][::-1]
    fig = go.Figure()
    fig.add_trace(go.Bar(y=labels, x=amt, orientation="h", marker=dict(color="rgba(0,0,0,0)", line=dict(color=INK2, width=1)),
                         width=0.7, hovertemplate="claim %{x:,.1f}<extra></extra>"))
    fig.add_trace(go.Bar(y=labels, x=hi, orientation="h", marker=dict(color="#a9c3d9"), width=0.7,
                         hovertemplate="recovered, high %{x:,.1f}<extra></extra>"))
    fig.add_trace(go.Bar(y=labels, x=lo, orientation="h", marker=dict(color=GREEN), width=0.36,
                         hovertemplate="recovered, low %{x:,.1f}<extra></extra>"))
    _layout(fig, 60 + 44 * len(labels))
    fig.update_layout(barmode="overlay")
    return fig


def earnings_bridge(e: dict) -> go.Figure:
    """Reported EBITDA → accepted add-backs → normalized, with management-adjusted as a reference."""
    def wrap(t, width=18):
        words, lines, cur = t.replace("(", "").replace(")", "").split(), [], ""
        for w in words:
            if len(cur) + len(w) + 1 > width and cur:
                lines.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        lines.append(cur)
        return "<br>".join(lines[:3])
    labels = ["Reported"] + [wrap(r["description"]) for r in e["rows"]] + ["Normalized"]
    measures = ["absolute"] + ["relative"] * len(e["rows"]) + ["total"]
    values = [e["reported"]] + [r["accepted"] for r in e["rows"]] + [0]
    text = [f"{e['reported']:,.1f}"] + [f"+{r['accepted']:,.1f}" + (f" of {r['amount']:,.1f}" if r["accepted"] != r["amount"] else "")
                                         for r in e["rows"]] + [f"{e['normalized']:,.1f}"]
    fig = go.Figure(go.Waterfall(x=labels, y=values, measure=measures, text=text, textposition="outside",
                                 connector=dict(line=dict(color=LINE, width=1)),
                                 increasing=dict(marker=dict(color="#7fa8c9")), totals=dict(marker=dict(color=GREEN)),
                                 decreasing=dict(marker=dict(color="#c0504d")), cliponaxis=False,
                                 hovertemplate="%{x}: %{text}<extra></extra>"))
    fig.add_hline(y=e["management_adjusted"], line=dict(color=BRASS, width=1.5, dash="dash"))
    fig.add_annotation(x=0, xref="paper", xanchor="left", y=e["management_adjusted"], yanchor="bottom",
                       text=f"Management adjusted {e['management_adjusted']:,.1f}", showarrow=False, font=dict(size=11, color=BRASS))
    _layout(fig, 300)
    fig.update_layout(margin=dict(l=10, r=20, t=30, b=40))
    fig.update_yaxes(gridcolor=LINE, range=[0, max(e["management_adjusted"], e["normalized"]) * 1.18])
    fig.update_xaxes(gridcolor="rgba(0,0,0,0)", tickfont=dict(size=11, color=INK), tickangle=0)
    fig.update_layout(height=330, margin=dict(l=10, r=20, t=30, b=70))
    return fig
