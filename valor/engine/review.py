"""Second-line review analytics on top of the valuation methods. All deterministic:

- earnings bridge: reported EBITDA + accepted share of each management add-back = normalized EBITDA
- downside case (performing): every method re-run with EBITDA, multiple and discount-rate shocks
- present value of recoveries and the implied specific reserve (troubled)
- policy tests (LTV, coverage) and the traffic-light status on variance to the first line
- assumption-by-assumption comparison with the first line's valuation package
"""

from __future__ import annotations

from valor.engine.base import r2


# ── earnings ─────────────────────────────────────────────────────────

def earnings_bridge(values: dict, addbacks: list[dict]) -> dict:
    reported = values.get("ebitda_ltm") or 0.0
    rows = []
    for a in addbacks:
        acc = values.get(f"addback.{a['adj_id']}", 0.0)
        rows.append({"adj_id": a["adj_id"], "description": a["description"], "category": a["category"],
                     "support": a["support"], "amount": a["amount"], "accepted_pct": acc,
                     "accepted": round(a["amount"] * acc, 4)})
    claimed = sum(r["amount"] for r in rows)
    accepted = sum(r["accepted"] for r in rows)
    return {"reported": reported, "rows": rows, "management_adjusted": round(reported + claimed, 4),
            "normalized": round(reported + accepted, 4), "claimed": round(claimed, 4), "accepted": round(accepted, 4),
            "accepted_share_of_reported": round(accepted / reported, 4) if reported else None}


def effective_values(values: dict, bridge: dict) -> dict:
    """The values the methods see: multiples apply to normalized EBITDA."""
    v = dict(values)
    v["ebitda_reported"] = values.get("ebitda_ltm")
    v["ebitda_ltm"] = bridge["normalized"]
    v["ebitda_normalized"] = bridge["normalized"]
    return v


# ── downside ─────────────────────────────────────────────────────────

def stressed_values(v: dict) -> dict:
    s = dict(v)
    shock = v.get("stress_ebitda", 0.0)
    mult = v.get("stress_multiple", 0.0)
    s["ebitda_ltm"] = v["ebitda_ltm"] * (1 + shock)
    for i in range(1, 6):
        if f"m_y{i}" in v:
            s[f"m_y{i}"] = v[f"m_y{i}"] * (1 + shock)
    for k in ("comps_low", "comps_mid", "comps_high", "txn_low", "txn_mid", "txn_high"):
        if k in v:
            s[k] = max(0.5, v[k] + mult)
    if "risk_free" in v:
        s["risk_free"] = v["risk_free"] + v.get("stress_wacc", 0.0)
    return s


# ── troubled: present value and reserve ─────────────────────────────

def reserve(conclusion: dict, values: dict) -> dict:
    years = values.get("recovery_years", 0.0) or 0.0
    rate = values.get("discount_rate", 0.0) or 0.0
    factor = 1 / (1 + rate) ** years
    exposure = values.get("bank_exposure") or 0.0
    out = {"years": years, "rate": rate, "pv_factor": round(factor, 6)}
    for side in ("low", "mid", "high"):
        pv = conclusion[side] * factor
        out[f"pv_{side}"] = r2(pv)
        out[f"reserve_{side}"] = r2(max(0.0, exposure - pv))
    # the low recovery case implies the high reserve
    out["reserve_range"] = (out["reserve_high"], out["reserve_low"])
    out["reserve_pct_mid"] = round(out["reserve_mid"] / exposure, 4) if exposure else None
    return out


# ── policy and traffic light ─────────────────────────────────────────

def rag(variance: float | None, policy: dict) -> str:
    if variance is None:
        return "grey"
    a = abs(variance)
    return "green" if a <= policy["rag_green"] else "amber" if a <= policy["rag_amber"] else "red"


def policy_tests(conclusion: dict, downside: dict | None, policy: dict) -> list[dict]:
    tests = []
    if conclusion["measure"] != "enterprise_value":
        return tests
    ltv = conclusion.get("ltv_mid")
    if ltv is not None:
        tests.append({"id": "ltv", "label": "Loan-to-value", "value": ltv, "limit": policy["max_ltv"], "kind": "max",
                      "unit": "pct", "pass": ltv <= policy["max_ltv"]})
    cov = conclusion.get("coverage_mid")
    if cov is not None:
        tests.append({"id": "coverage", "label": "Coverage of commitment", "value": cov, "limit": policy["min_coverage"],
                      "kind": "min", "unit": "x", "pass": cov >= policy["min_coverage"]})
    if downside and downside.get("ltv_mid") is not None:
        tests.append({"id": "ltv_downside", "label": "Loan-to-value, downside", "value": downside["ltv_mid"],
                      "limit": policy["max_ltv_downside"], "kind": "max", "unit": "pct",
                      "pass": downside["ltv_mid"] <= policy["max_ltv_downside"]})
    return tests


# ── first line vs second line ────────────────────────────────────────

def first_line_comparison(first: dict, values: dict, bridge: dict, methods: dict, conclusion: dict, policy: dict) -> list[dict]:
    """Rows of (assumption, first line, second line, unit). Variance is relative except for rates (pt)."""
    if not first:
        return []
    rows = []

    def add(label, fl, sl, unit, pts=False):
        if fl is None or sl is None:
            return
        if pts:
            delta = sl - fl
            status = "green" if abs(delta) < 0.0025 else "amber" if abs(delta) <= 0.01 else "red"
        else:
            delta = (sl - fl) / fl if fl else None
            status = rag(delta, policy)
        rows.append({"assumption": label, "first_line": fl, "second_line": sl, "unit": unit, "delta": delta,
                     "delta_kind": "pt" if pts else "rel", "status": status})

    add("EBITDA used", first.get("ebitda_used"), bridge["normalized"], "musd")
    if conclusion["measure"] == "enterprise_value":
        add("EV / EBITDA multiple", first.get("multiple_used"), values.get("comps_mid"), "x")
        if "dcf" in methods:
            add("WACC", first.get("wacc"), methods["dcf"]["details"]["wacc"]["wacc"], "pct", pts=True)
        add("Terminal growth", first.get("terminal_growth"), values.get("terminal_growth"), "pct", pts=True)
        add("Revenue growth, year 1", first.get("growth_y1"), values.get("g_y1"), "pct", pts=True)
        add("Enterprise value", first.get("value_musd"), conclusion["mid"], "musd")
    else:
        lo, hi = values.get("dist_mult_low"), values.get("dist_mult_high")
        if lo is not None and hi is not None:
            add("Distressed EV / EBITDA", first.get("multiple_used"), (lo + hi) / 2, "x")
        add("Recovery, % of exposure", first.get("recovery_pct"), conclusion.get("recovery_pct_mid"), "pct", pts=True)
        add("Bank recovery", first.get("value_musd"), conclusion["mid"], "musd")
    return rows


def suggested_verdict(status: str, tests: list[dict], high_checks: int) -> str:
    if status == "red" or any(not t["pass"] for t in tests):
        return "do_not_concur" if status == "red" else "concur_with_exceptions"
    if status == "amber" or high_checks:
        return "concur_with_exceptions"
    return "concur"


VERDICTS = {
    "concur": "Concur",
    "concur_with_exceptions": "Concur with exceptions",
    "do_not_concur": "Do not concur",
}
