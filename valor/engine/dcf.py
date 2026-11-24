"""Discounted cash flow (unlevered FCF, end-of-year discounting, Gordon growth terminal value).

Translated from the master workbook's `DCF` sheet (workbook/master_valuation.xlsx) and verified
against its outputs by tests/test_workbook_parity.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from valor.engine.base import MethodResult, r2

VERSION = "dcf-1.0 (from workbook DCF sheet)"


@dataclass
class WACCInputs:
    risk_free: float
    erp: float
    beta_unlevered: float
    size_premium: float
    debt_to_cap: float
    cost_of_debt: float
    tax_rate: float


@dataclass
class DCFInputs:
    base_revenue: float
    growth: list[float]              # years 1..5
    margin: list[float]              # EBITDA margin, years 1..5
    da_pct_rev: float
    capex_pct_rev: float
    nwc_pct_incr_rev: float
    tax_rate: float
    wacc: WACCInputs
    terminal_growth: float
    wacc_step: float = 0.01
    growth_step: float = 0.005


def wacc(w: WACCInputs) -> dict:
    """Hamada re-levering: beta_L = beta_U * (1 + (1 - t) * D/E)."""
    d_e = w.debt_to_cap / (1 - w.debt_to_cap)
    beta_l = w.beta_unlevered * (1 + (1 - w.tax_rate) * d_e)
    ke = w.risk_free + beta_l * w.erp + w.size_premium
    kd = w.cost_of_debt * (1 - w.tax_rate)
    value = (1 - w.debt_to_cap) * ke + w.debt_to_cap * kd
    return {"levered_beta": beta_l, "cost_of_equity": ke, "after_tax_cost_of_debt": kd, "wacc": value}


def project(inp: DCFInputs) -> list[dict]:
    rows, prev = [], inp.base_revenue
    for t, (g, m) in enumerate(zip(inp.growth, inp.margin), start=1):
        rev = prev * (1 + g)
        ebitda = rev * m
        da = rev * inp.da_pct_rev
        ebit = ebitda - da
        tax = ebit * inp.tax_rate
        capex = rev * inp.capex_pct_rev
        d_nwc = (rev - prev) * inp.nwc_pct_incr_rev
        fcf = ebit - tax + da - capex - d_nwc
        rows.append({"year": t, "revenue": rev, "ebitda": ebitda, "d_and_a": da, "ebit": ebit, "taxes": tax,
                     "capex": capex, "change_nwc": d_nwc, "fcf": fcf})
        prev = rev
    return rows


def enterprise_value(rows: list[dict], rate: float, g: float) -> dict:
    if rate <= g:
        raise ValueError(f"WACC ({rate:.2%}) must exceed terminal growth ({g:.2%})")
    pv_fcf = sum(r["fcf"] / (1 + rate) ** r["year"] for r in rows)
    n = rows[-1]["year"]
    tv = rows[-1]["fcf"] * (1 + g) / (rate - g)
    pv_tv = tv / (1 + rate) ** n
    return {"pv_fcf": pv_fcf, "terminal_value": tv, "pv_terminal": pv_tv, "ev": pv_fcf + pv_tv}


def run(inp: DCFInputs) -> MethodResult:
    k = wacc(inp.wacc)
    rows = project(inp)
    base = enterprise_value(rows, k["wacc"], inp.terminal_growth)
    low = enterprise_value(rows, k["wacc"] + inp.wacc_step, inp.terminal_growth - inp.growth_step)["ev"]
    high = enterprise_value(rows, k["wacc"] - inp.wacc_step, inp.terminal_growth + inp.growth_step)["ev"]
    grid_w = [k["wacc"] + d for d in (-inp.wacc_step, -inp.wacc_step / 2, 0, inp.wacc_step / 2, inp.wacc_step)]
    grid_g = [inp.terminal_growth + d for d in (-inp.growth_step, 0, inp.growth_step)]
    grid = [[r2(enterprise_value(rows, w, g)["ev"]) for g in grid_g] for w in grid_w]
    terminal_ebitda = rows[-1]["ebitda"]
    return MethodResult(
        method="dcf", label="Discounted cash flow", low=r2(low), mid=r2(base["ev"]), high=r2(high),
        version=VERSION,
        details={
            "wacc": {key: round(v, 6) for key, v in k.items()},
            "projection": [{key: (round(v, 4) if key != "year" else v) for key, v in r.items()} for r in rows],
            "pv_fcf": r2(base["pv_fcf"]), "terminal_value": r2(base["terminal_value"]),
            "pv_terminal": r2(base["pv_terminal"]),
            "terminal_share": round(base["pv_terminal"] / base["ev"], 4),
            "implied_exit_multiple": round(base["terminal_value"] / terminal_ebitda, 2) if terminal_ebitda else None,
            "sensitivity": {"wacc": [round(w, 4) for w in grid_w], "growth": [round(g, 4) for g in grid_g], "ev": grid},
        },
    )


def build_inputs(v: dict, claims: list[dict] | None = None, wacc_step: float = 0.01, growth_step: float = 0.005) -> DCFInputs:
    return DCFInputs(
        base_revenue=v["revenue_ltm"],
        growth=[v[f"g_y{i}"] for i in range(1, 6)],
        margin=[v[f"m_y{i}"] for i in range(1, 6)],
        da_pct_rev=v["da_pct_rev"], capex_pct_rev=v["capex_pct_rev"], nwc_pct_incr_rev=v["nwc_pct_incr_rev"],
        tax_rate=v["tax_rate"],
        wacc=WACCInputs(risk_free=v["risk_free"], erp=v["erp"], beta_unlevered=v["beta_unlevered"],
                        size_premium=v["size_premium"], debt_to_cap=v["debt_to_cap"],
                        cost_of_debt=v["cost_of_debt"], tax_rate=v["tax_rate"]),
        terminal_growth=v["terminal_growth"], wacc_step=wacc_step, growth_step=growth_step,
    )
