"""Discounted cash flow method ("dcf") for Valor's deterministic valuation engine.

Source: master valuation workbook (MOCK), sheet "DCF"
("Discounted cash flow · end-of-year discounting · Gordon growth").

Outputs and where they come from:
    details["wacc"]            <- DCF!B6
    mid                        <- DCF!B23  (Enterprise value = B20 + B22)
    low                        <- DCF!B24  (EV at WACC + wacc_step, g - growth_step)
    high                       <- DCF!B25  (EV at WACC - wacc_step, g + growth_step)
    details["terminal_value"]  <- DCF!B21

Intermediate rows reproduced in details:
    B3 levered beta, B4 cost of equity, B5 after-tax cost of debt,
    rows 9-18 (revenue, EBITDA, D&A, EBIT, taxes, capex, change in NWC,
    free cash flow, discount factor, PV of FCF), B20 sum of PV of FCF,
    B22 PV of terminal value.

Sensitivity steps come from Inputs!C31 (wacc_step = 0.01) and Inputs!C32
(growth_step = 0.005). They are not engine input keys, so the workbook
constants are the defaults; they can be overridden with values["wacc_step"]
and values["growth_step"] if supplied.

All money figures are USD millions. Rates are decimals.
"""

from __future__ import annotations

from dataclasses import dataclass

from valor.engine.base import MethodResult, r2

VERSION = "1.0.0"

METHOD = "dcf"
LABEL = "Discounted cash flow"

# Workbook constants (Inputs!C31, Inputs!C32)
DEFAULT_WACC_STEP = 0.01
DEFAULT_GROWTH_STEP = 0.005

YEARS = (1, 2, 3, 4, 5)  # DCF!C8:G8 (B8 = 0 is the LTM base year)


@dataclass
class DCFInputs:
    revenue_ltm: float        # Inputs!C4
    growth: tuple             # Inputs!C6:C10 (g_y1..g_y5)
    margin: tuple             # Inputs!C11:C15 (m_y1..m_y5)
    da_pct_rev: float         # Inputs!C16
    capex_pct_rev: float      # Inputs!C17
    nwc_pct_incr_rev: float   # Inputs!C18
    tax_rate: float           # Inputs!C19
    risk_free: float          # Inputs!C20
    erp: float                # Inputs!C21
    beta_unlevered: float     # Inputs!C22
    size_premium: float       # Inputs!C23
    debt_to_cap: float        # Inputs!C24
    cost_of_debt: float       # Inputs!C25
    terminal_growth: float    # Inputs!C26
    wacc_step: float = DEFAULT_WACC_STEP      # Inputs!C31
    growth_step: float = DEFAULT_GROWTH_STEP  # Inputs!C32


def _get(values: dict, key: str) -> float:
    if key not in values or values[key] is None:
        raise KeyError(f"dcf: missing required input '{key}'")
    return float(values[key])


def build_inputs(values: dict, claims: list[dict] | None = None) -> DCFInputs:
    """Map engine input keys to the DCF inputs. Claims are not used by this method."""
    return DCFInputs(
        revenue_ltm=_get(values, "revenue_ltm"),
        growth=tuple(_get(values, f"g_y{n}") for n in YEARS),
        margin=tuple(_get(values, f"m_y{n}") for n in YEARS),
        da_pct_rev=_get(values, "da_pct_rev"),
        capex_pct_rev=_get(values, "capex_pct_rev"),
        nwc_pct_incr_rev=_get(values, "nwc_pct_incr_rev"),
        tax_rate=_get(values, "tax_rate"),
        risk_free=_get(values, "risk_free"),
        erp=_get(values, "erp"),
        beta_unlevered=_get(values, "beta_unlevered"),
        size_premium=_get(values, "size_premium"),
        debt_to_cap=_get(values, "debt_to_cap"),
        cost_of_debt=_get(values, "cost_of_debt"),
        terminal_growth=_get(values, "terminal_growth"),
        wacc_step=float(values.get("wacc_step", DEFAULT_WACC_STEP)),
        growth_step=float(values.get("growth_step", DEFAULT_GROWTH_STEP)),
    )


def _div(num: float, den: float, cell: str) -> float:
    # Excel returns #DIV/0! here; surface it rather than return a number.
    if den == 0:
        raise ValueError(f"dcf: division by zero in {cell} (workbook would show #DIV/0!)")
    return num / den


def _ev_at(fcf: list[float], wacc: float, g: float, cell: str) -> float:
    """Literal form of DCF!B24 / B25: discount FCF and Gordon TV at a given WACC and g."""
    total = 0.0
    for n, cf in zip(YEARS, fcf):
        total = total + cf / (1 + wacc) ** n
    tv = _div(fcf[-1] * (1 + g), wacc - g, cell)
    return total + tv / (1 + wacc) ** YEARS[-1]


def run(inputs: DCFInputs) -> MethodResult:
    i = inputs
    t = i.tax_rate
    dc = i.debt_to_cap

    # --- Discount rate (DCF!B3:B6) ---
    levered_beta = i.beta_unlevered * (1 + _div((1 - t) * dc, 1 - dc, "DCF!B3"))  # B3
    cost_of_equity = i.risk_free + levered_beta * i.erp + i.size_premium            # B4
    kd_after_tax = i.cost_of_debt * (1 - t)                                          # B5
    wacc = (1 - dc) * cost_of_equity + dc * kd_after_tax                             # B6

    # --- Projection (DCF!B9:G18) ---
    revenue = [i.revenue_ltm]  # B9
    for g in i.growth:          # C9:G9
        revenue.append(revenue[-1] * (1 + g))

    ebitda, da, ebit, taxes, capex, d_nwc, fcf, dfac, pv = ([] for _ in range(9))
    for k, n in enumerate(YEARS):
        rev = revenue[k + 1]
        e = rev * i.margin[k]                                   # row 10
        d = rev * i.da_pct_rev                                  # row 11
        eb = e - d                                              # row 12
        tx = eb * t                                             # row 13 (no floor at zero)
        cx = rev * i.capex_pct_rev                              # row 14
        nw = (rev - revenue[k]) * i.nwc_pct_incr_rev            # row 15
        f = eb - tx + d - cx - nw                               # row 16
        df = 1 / (1 + wacc) ** n                                # row 17
        ebitda.append(e); da.append(d); ebit.append(eb); taxes.append(tx)
        capex.append(cx); d_nwc.append(nw); fcf.append(f); dfac.append(df)
        pv.append(f * df)                                       # row 18

    sum_pv = sum(pv)                                                                     # B20
    terminal_value = _div(fcf[-1] * (1 + i.terminal_growth), wacc - i.terminal_growth,
                          "DCF!B21")                                                     # B21
    pv_tv = terminal_value * dfac[-1]                                                    # B22
    ev_mid = sum_pv + pv_tv                                                              # B23

    wacc_low_case = wacc + i.wacc_step
    g_low_case = i.terminal_growth - i.growth_step
    wacc_high_case = wacc - i.wacc_step
    g_high_case = i.terminal_growth + i.growth_step
    ev_low = _ev_at(fcf, wacc_low_case, g_low_case, "DCF!B24")                           # B24
    ev_high = _ev_at(fcf, wacc_high_case, g_high_case, "DCF!B25")                        # B25

    warnings = []
    if wacc - i.terminal_growth <= 0:
        warnings.append("WACC does not exceed terminal growth; Gordon terminal value is not meaningful.")
    if wacc_high_case - g_high_case <= 0:
        warnings.append("High case: WACC - step does not exceed g + step; DCF!B25 is not meaningful.")
    if any(x < 0 for x in ebit):
        warnings.append("Negative EBIT in projection; workbook books a negative tax (no floor).")

    details = {
        "sheet": "DCF",
        "levered_beta": levered_beta,                 # B3
        "cost_of_equity": cost_of_equity,             # B4
        "after_tax_cost_of_debt": kd_after_tax,       # B5
        "wacc": wacc,                                 # B6
        "years": list(YEARS),
        "revenue_base": revenue[0],                   # B9
        "revenue": [r2(x) for x in revenue[1:]],      # C9:G9
        "ebitda": [r2(x) for x in ebitda],            # C10:G10
        "da": [r2(x) for x in da],                    # C11:G11
        "ebit": [r2(x) for x in ebit],                # C12:G12
        "taxes": [r2(x) for x in taxes],              # C13:G13
        "capex": [r2(x) for x in capex],              # C14:G14
        "change_in_nwc": [r2(x) for x in d_nwc],      # C15:G15
        "fcf": [r2(x) for x in fcf],                  # C16:G16
        "discount_factor": dfac,                      # C17:G17
        "pv_fcf": [r2(x) for x in pv],                # C18:G18
        "sum_pv_fcf": r2(sum_pv),                     # B20
        "terminal_value": r2(terminal_value),         # B21
        "pv_terminal_value": r2(pv_tv),               # B22
        "terminal_value_share_of_ev": (pv_tv / ev_mid) if ev_mid else None,
        "terminal_growth": i.terminal_growth,
        "low_case": {"wacc": wacc_low_case, "terminal_growth": g_low_case},
        "high_case": {"wacc": wacc_high_case, "terminal_growth": g_high_case},
        "wacc_step": i.wacc_step,
        "growth_step": i.growth_step,
        "warnings": warnings,
    }

    return MethodResult(
        method=METHOD,
        label=LABEL,
        low=r2(ev_low),
        mid=r2(ev_mid),
        high=r2(ev_high),
        measure="enterprise_value",
        details=details,
        version=VERSION,
    )
