"""Deterministic review checks run after every valuation. They are the evidence the agent
reasons over, and the whole recommendation set when the agent runs in mock mode.
Thresholds are prototype assumptions: tune them here."""

from __future__ import annotations

import statistics

THRESHOLDS = {
    "terminal_growth_max": 0.030,
    "terminal_share_max": 0.75,
    "exit_multiple_gap": 0.30,
    "method_dispersion": 1.40,
    "growth_vs_history_pp": 0.03,
    "margin_expansion_pp": 0.02,
    "min_peers": 5,
    "recovery_rate_premium": 0.0,
}


def _check(cid, severity, title, detail, field=None, current=None, suggested=None):
    return {"id": cid, "severity": severity, "title": title, "detail": detail, "field": field,
            "current": current, "suggested": suggested}


def run(template: dict, values: dict, valuation: dict, history: dict, policy: dict | None = None) -> list[dict]:
    """history: {"revenue_cagr": float, "ltm_margin": float, "n_comps": int, "n_txns": int,
                 "recovery_table": {class: (low, high)}}"""
    out = []
    policy = policy or {}
    methods = {m["method"]: m for m in valuation["methods"]}
    c = valuation["conclusion"]
    e = valuation.get("earnings")

    if e and e["reported"]:
        share = e["accepted"] / e["reported"]
        cap = policy.get("addback_cap", 0.2)
        if share > cap:
            out.append(_check("addback_cap", "high", "Accepted add-backs exceed policy cap",
                              f"Accepted add-backs are {share:.0%} of reported EBITDA, above the {cap:.0%} cap."))
        for r in e["rows"]:
            if r["category"] == "synergies" and r["accepted_pct"] > 0:
                out.append(_check(f"syn_{r['adj_id']}", "medium", "Expected synergies credited",
                                  f"{r['description']}: {r['accepted_pct']:.0%} accepted. Synergies not yet realized are "
                                  "normally excluded from collateral value.", f"addback.{r['adj_id']}", r["accepted_pct"], 0.0))
        gap = e["management_adjusted"] - e["normalized"]
        if gap > 0 and e["management_adjusted"]:
            out.append(_check("ebitda_gap", "medium" if gap / e["management_adjusted"] > 0.1 else "low",
                              "First line relies on management-adjusted EBITDA",
                              f"Normalized EBITDA is {e['normalized']:,.1f} against management's {e['management_adjusted']:,.1f} "
                              f"({-gap / e['management_adjusted']:+.0%})."))

    for t in valuation.get("policy_tests") or []:
        if not t["pass"]:
            val = f"{t['value']:.0%}" if t["unit"] == "pct" else f"{t['value']:.2f}x"
            lim = f"{t['limit']:.0%}" if t["unit"] == "pct" else f"{t['limit']:.2f}x"
            out.append(_check(f"policy_{t['id']}", "high", f"{t['label']} outside policy",
                              f"{val} against a {'maximum' if t['kind'] == 'max' else 'minimum'} of {lim}."))

    if c.get("weights_normalized"):
        out.append(_check("weights", "high", "Reconciliation weights do not sum to 100%",
                          f"Weights total {c['weights_total']:.0%}; the engine normalized them. Fix the weights so the conclusion is explicit."))

    if c.get("variance_flag"):
        out.append(_check("first_line_gap", "high", "Material variance to the first-line valuation",
                          f"Second-line midpoint differs from the first line by {c['vs_first_line']:+.1%} "
                          f"({c['mid']:,.1f} vs {c['first_line_value']:,.1f})."))

    mids = [m["mid"] for m in valuation["methods"] if m["mid"] > 0]
    if len(mids) > 1 and max(mids) / min(mids) > THRESHOLDS["method_dispersion"]:
        out.append(_check("dispersion", "medium", "Wide dispersion between methods",
                          f"Highest method midpoint is {max(mids) / min(mids):.2f}x the lowest; consider reweighting toward the better-supported method."))

    if "dcf" in methods:
        d = methods["dcf"]["details"]
        g = values["terminal_growth"]
        if g > THRESHOLDS["terminal_growth_max"]:
            out.append(_check("tg_high", "high", "Terminal growth above long-run nominal GDP",
                              f"Terminal growth of {g:.2%} exceeds the {THRESHOLDS['terminal_growth_max']:.1%} ceiling.",
                              "terminal_growth", g, THRESHOLDS["terminal_growth_max"] - 0.005))
        if d["terminal_share"] > THRESHOLDS["terminal_share_max"]:
            out.append(_check("tv_share", "medium", "Terminal value dominates the DCF",
                              f"Terminal value is {d['terminal_share']:.0%} of DCF enterprise value; the result rests on long-run assumptions."))
        comps_mid = values.get("comps_mid")
        if comps_mid and d.get("implied_exit_multiple"):
            gap = d["implied_exit_multiple"] / comps_mid - 1
            if abs(gap) > THRESHOLDS["exit_multiple_gap"]:
                out.append(_check("exit_multiple", "medium", "DCF implied exit multiple out of line with peers",
                                  f"Terminal value implies {d['implied_exit_multiple']:.1f}x EBITDA vs a peer median of {comps_mid:.1f}x ({gap:+.0%})."))
        cagr = history.get("revenue_cagr")
        g1 = values.get("g_y1")
        if cagr is not None and g1 is not None and g1 > cagr + THRESHOLDS["growth_vs_history_pp"]:
            out.append(_check("growth_y1", "medium", "Year-1 growth above recent history",
                              f"Management projects {g1:.1%} growth in year 1 against a {cagr:.1%} two-year historical CAGR.",
                              "g_y1", g1, round(cagr, 4)))
        ltm_m = history.get("ltm_margin")
        m5 = values.get("m_y5")
        if ltm_m is not None and m5 is not None and m5 > ltm_m + THRESHOLDS["margin_expansion_pp"]:
            out.append(_check("margin_exp", "medium", "Projected margin expansion",
                              f"Year-5 EBITDA margin of {m5:.1%} is {(m5 - ltm_m) * 100:.1f}pt above the LTM margin of {ltm_m:.1%}.",
                              "m_y5", m5, round(ltm_m + THRESHOLDS["margin_expansion_pp"] / 2, 4)))

    if "trading_comps" in methods and history.get("n_comps", 99) < THRESHOLDS["min_peers"]:
        out.append(_check("thin_comps", "low", "Thin peer set", f"Only {history['n_comps']} trading comparables in the sector."))

    if "liquidation" in methods:
        table = history.get("recovery_table", {})
        key_map = {"ar": "accounts_receivable"}
        for k in ("cash", "ar", "inventory", "ppe", "intangibles", "other"):
            ref = table.get(key_map.get(k, k))
            if not ref:
                continue
            for side, i in (("low", 0), ("high", 1)):
                v = values.get(f"rr_{k}_{side}")
                if v is not None and v > ref[i] + 1e-9:
                    out.append(_check(f"rr_{k}_{side}", "medium", f"Recovery rate above market reference ({k}, {side})",
                                      f"{v:.0%} vs reference {ref[i]:.0%}.", f"rr_{k}_{side}", v, ref[i]))
        if values.get("book_intangibles", 0) > 0 and values.get("rr_intangibles_low", 0) > 0:
            out.append(_check("intangibles_low", "low", "Intangibles given value in the low case",
                              "Liquidation low cases usually ascribe no value to intangibles.",
                              "rr_intangibles_low", values["rr_intangibles_low"], 0.0))

    if "distressed_gc" in methods:
        ltm = history.get("ltm_ebitda")
        avg3 = history.get("avg3_ebitda")
        norm = e["normalized"] if e else values.get("ebitda_normalized")
        if norm and avg3 and ltm and norm > ltm * 1.05:
            out.append(_check("norm_ebitda", "medium", "Normalized EBITDA above LTM",
                              f"Normalized EBITDA of {norm:,.1f} exceeds LTM EBITDA of {ltm:,.1f}; support the add-backs."))
        if norm and avg3 and ltm and abs(norm - ltm) < 1e-6 and avg3 > ltm * 1.3:
            out.append(_check("ebitda_trend", "low", "EBITDA is declining fast",
                              f"LTM EBITDA ({ltm:,.1f}) is well below the three-year average ({avg3:,.1f}); "
                              "the distressed case uses LTM, which is the conservative choice."))
    return out


def history_from_tables(tables: dict) -> dict:
    fin = tables["financials"]
    h: dict = {}
    if len(fin) >= 3:
        r = fin.revenue.tolist()
        h["revenue_cagr"] = (r[-1] / r[-3]) ** 0.5 - 1
    if not fin.empty:
        last = fin.iloc[-1]
        h["ltm_margin"] = float(last.ebitda / last.revenue)
        h["ltm_ebitda"] = float(last.ebitda)
        h["avg3_ebitda"] = float(statistics.mean(fin.ebitda.tail(3)))
    h["n_comps"] = len(tables["trading_comps"])
    h["n_txns"] = len(tables["precedent_transactions"])
    rr = tables["recovery_rates"]
    h["recovery_table"] = {row.asset_class: (float(row.recovery_low), float(row.recovery_high)) for row in rr.itertuples()}
    return h
