"""Build the mock master valuation workbook (workbook/master_valuation.xlsx) and its cell map
(workbook/mapping.yaml).

It stands in for the bank's real Excel master: tabs for DCF, trading comps, precedent
transactions and liquidation analysis, written as live Excel formulas. The sample deals are
Harbor Point Logistics (D-1001, performing tabs) and Ironvale Manufacturing (D-2001,
liquidation tab), with inputs taken from the same mock tables the app uses.

mapping.yaml tells the parity test and the translation workflow which cell holds each engine
input and each output. When the real workbook arrives, write its mapping by hand (or have
`python -m valor.excel propose` draft it) and the same tests apply.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from valor.data.mock import MockDataSource  # noqa: E402
from valor.data.resolvers import PullContext, resolve  # noqa: E402
from valor.workflow import template  # noqa: E402

BOLD = Font(bold=True)
INPUT = PatternFill("solid", fgColor="FFF2CC")       # yellow = hard-coded input
HEAD = Font(bold=True, color="7D2230")


def values_for(deal_id: str, wf: str) -> tuple[dict, PullContext]:
    ctx = PullContext(MockDataSource(), deal_id)
    vals = {}
    for g in template(wf)["input_groups"]:
        for i in g.get("inputs", []):
            vals[i["key"]] = resolve(i["source"], ctx).value
    return vals, ctx


def main() -> None:
    perf, pctx = values_for("D-1001", "performing")
    trbl, tctx = values_for("D-2001", "troubled")
    wb = Workbook()
    mapping: dict = {"performing": {"inputs": {}, "outputs": {}}, "troubled": {"inputs": {}, "outputs": {}, "claims": []}}
    mi, mo = mapping["performing"]["inputs"], mapping["performing"]["outputs"]

    # ── Inputs ──
    ws = wb.active
    ws.title = "Inputs"
    ws["A1"], ws["A1"].font = "Master valuation workbook (MOCK) · Harbor Point Logistics · USD millions", HEAD
    ws.append([])
    ws.append(["Key", "Input", "Value"])
    for c in ws[3]:
        c.font = BOLD
    ref = {}
    rows = [("revenue_ltm", "Revenue, LTM"), ("ebitda_ltm", "EBITDA, LTM")]
    rows += [(f"g_y{i}", f"Revenue growth, year {i}") for i in range(1, 6)]
    rows += [(f"m_y{i}", f"EBITDA margin, year {i}") for i in range(1, 6)]
    rows += [("da_pct_rev", "D&A % revenue"), ("capex_pct_rev", "Capex % revenue"),
             ("nwc_pct_incr_rev", "NWC % incremental revenue"), ("tax_rate", "Tax rate"),
             ("risk_free", "Risk-free rate"), ("erp", "Equity risk premium"), ("beta_unlevered", "Unlevered beta"),
             ("size_premium", "Size premium"), ("debt_to_cap", "Debt / capital"), ("cost_of_debt", "Pre-tax cost of debt"),
             ("terminal_growth", "Terminal growth"), ("private_discount", "Private-company discount"),
             ("w_dcf", "Weight DCF"), ("w_comps", "Weight comps"), ("w_txn", "Weight precedents"),
             ("wacc_step", "Sensitivity: WACC step"), ("growth_step", "Sensitivity: growth step")]
    extra = {"wacc_step": 0.01, "growth_step": 0.005}
    for key, label in rows:
        ws.append([key, label, perf.get(key, extra.get(key))])
        r = ws.max_row
        ws.cell(r, 3).fill = INPUT
        ref[key] = f"Inputs!$C${r}"
        if key not in extra:
            mi[key] = f"Inputs!C{r}"
    ws.column_dimensions["B"].width = 34

    # ── Comps ──
    wc = wb.create_sheet("Comps")
    wc["A1"], wc["A1"].font = "Trading comparables (EV / EBITDA)", HEAD
    wc.append(["Ticker", "Company", "EV/EBITDA"])
    for c in wc[2]:
        c.font = BOLD
    for row in pctx.comps.itertuples():
        wc.append([row.ticker, row.company_name, row.ev_ebitda])
        wc.cell(wc.max_row, 3).fill = INPUT
    last = wc.max_row
    rng = f"C3:C{last}"
    wc.append([])
    stats = [("comps_low", "25th percentile", f"=QUARTILE.INC({rng},1)"), ("comps_mid", "Median", f"=MEDIAN({rng})"),
             ("comps_high", "75th percentile", f"=QUARTILE.INC({rng},3)")]
    for key, label, f in stats:
        wc.append(["", label, f])
        ref[key] = f"Comps!$C${wc.max_row}"
        mi[key] = f"Comps!C{wc.max_row}"
    wc.append([])
    wc.append(["", "EBITDA after private discount", f"={ref['ebitda_ltm']}*(1-{ref['private_discount']})"])
    base = f"Comps!$C${wc.max_row}"
    for key, side in (("comps_low", "low"), ("comps_mid", "mid"), ("comps_high", "high")):
        wc.append(["", f"Enterprise value, {side}", f"={base}*{ref[key]}"])
        mo[f"trading_comps.{side}"] = f"Comps!C{wc.max_row}"
        ref[f"comps_ev_{side}"] = f"Comps!$C${wc.max_row}"
    wc.column_dimensions["B"].width = 34

    # ── Precedents ──
    wp = wb.create_sheet("Precedents")
    wp["A1"], wp["A1"].font = "Precedent transactions (EV / EBITDA, non-distressed)", HEAD
    wp.append(["Close date", "Target", "EV/EBITDA"])
    for c in wp[2]:
        c.font = BOLD
    for row in pctx.txns.itertuples():
        wp.append([row.close_date, row.target, row.ev_ebitda])
        wp.cell(wp.max_row, 3).fill = INPUT
    rng = f"C3:C{wp.max_row}"
    wp.append([])
    for key, label, f in (("txn_low", "25th percentile", f"=QUARTILE.INC({rng},1)"), ("txn_mid", "Median", f"=MEDIAN({rng})"),
                          ("txn_high", "75th percentile", f"=QUARTILE.INC({rng},3)")):
        wp.append(["", label, f])
        ref[key] = f"Precedents!$C${wp.max_row}"
        mi[key] = f"Precedents!C{wp.max_row}"
    wp.append([])
    for key, side in (("txn_low", "low"), ("txn_mid", "mid"), ("txn_high", "high")):
        wp.append(["", f"Enterprise value, {side}", f"={ref['ebitda_ltm']}*{ref[key]}"])
        mo[f"precedents.{side}"] = f"Precedents!C{wp.max_row}"
        ref[f"txn_ev_{side}"] = f"Precedents!$C${wp.max_row}"
    wp.column_dimensions["B"].width = 34

    # ── DCF ──
    wd = wb.create_sheet("DCF", 1)
    wd["A1"], wd["A1"].font = "Discounted cash flow · end-of-year discounting · Gordon growth", HEAD
    t = ref["tax_rate"]
    wd["A3"], wd["B3"] = "Levered beta", f"={ref['beta_unlevered']}*(1+(1-{t})*{ref['debt_to_cap']}/(1-{ref['debt_to_cap']}))"
    wd["A4"], wd["B4"] = "Cost of equity", f"={ref['risk_free']}+B3*{ref['erp']}+{ref['size_premium']}"
    wd["A5"], wd["B5"] = "After-tax cost of debt", f"={ref['cost_of_debt']}*(1-{t})"
    wd["A6"], wd["B6"] = "WACC", f"=(1-{ref['debt_to_cap']})*B4+{ref['debt_to_cap']}*B5"
    mo["dcf.wacc"] = "DCF!B6"
    labels = ["Year", "Revenue", "EBITDA", "D&A", "EBIT", "Taxes", "Capex", "Change in NWC", "Free cash flow", "Discount factor", "PV of FCF"]
    for i, lab in enumerate(labels):
        wd.cell(8 + i, 1, lab).font = BOLD if i == 0 else Font()
    wd.cell(8, 2, 0)
    wd.cell(9, 2, f"={ref['revenue_ltm']}")
    cols = "CDEFG"
    for n, col in enumerate(cols, start=1):
        prev = chr(ord(col) - 1)
        wd[f"{col}8"] = n
        wd[f"{col}9"] = f"={prev}9*(1+{ref[f'g_y{n}']})"
        wd[f"{col}10"] = f"={col}9*{ref[f'm_y{n}']}"
        wd[f"{col}11"] = f"={col}9*{ref['da_pct_rev']}"
        wd[f"{col}12"] = f"={col}10-{col}11"
        wd[f"{col}13"] = f"={col}12*{t}"
        wd[f"{col}14"] = f"={col}9*{ref['capex_pct_rev']}"
        wd[f"{col}15"] = f"=({col}9-{prev}9)*{ref['nwc_pct_incr_rev']}"
        wd[f"{col}16"] = f"={col}12-{col}13+{col}11-{col}14-{col}15"
        wd[f"{col}17"] = f"=1/(1+$B$6)^{col}8"
        wd[f"{col}18"] = f"={col}16*{col}17"
    g = ref["terminal_growth"]
    wd["A20"], wd["B20"] = "Sum of PV of FCF", "=SUM(C18:G18)"
    wd["A21"], wd["B21"] = "Terminal value", f"=G16*(1+{g})/(B6-{g})"
    wd["A22"], wd["B22"] = "PV of terminal value", "=B21*G17"
    wd["A23"], wd["B23"] = "Enterprise value", "=B20+B22"
    wd["A23"].font = BOLD
    ws_, gs_ = ref["wacc_step"], ref["growth_step"]

    def ev_at(w: str, gg: str) -> str:
        pv = "+".join(f"{c}16/(1+{w})^{c}8" for c in cols)
        return f"={pv}+G16*(1+{gg})/({w}-{gg})/(1+{w})^G8"

    wd["A24"], wd["B24"] = "Enterprise value, low (WACC +step, g −step)", ev_at(f"(B6+{ws_})", f"({g}-{gs_})")
    wd["A25"], wd["B25"] = "Enterprise value, high (WACC −step, g +step)", ev_at(f"(B6-{ws_})", f"({g}+{gs_})")
    mo.update({"dcf.mid": "DCF!B23", "dcf.low": "DCF!B24", "dcf.high": "DCF!B25", "dcf.terminal_value": "DCF!B21"})
    wd.column_dimensions["A"].width = 44

    # ── Summary (performing) ──
    wsum = wb.create_sheet("Summary")
    wsum["A1"], wsum["A1"].font = "Reconciliation", HEAD
    wsum.append(["Method", "Low", "Mid", "High", "Weight"])
    wsum.append(["DCF", "=DCF!B24", "=DCF!B23", "=DCF!B25", f"={ref['w_dcf']}"])
    wsum.append(["Trading comps", f"={ref['comps_ev_low']}", f"={ref['comps_ev_mid']}", f"={ref['comps_ev_high']}", f"={ref['w_comps']}"])
    wsum.append(["Precedents", f"={ref['txn_ev_low']}", f"={ref['txn_ev_mid']}", f"={ref['txn_ev_high']}", f"={ref['w_txn']}"])
    for col, side in (("B", "low"), ("C", "mid"), ("D", "high")):
        wsum[f"{col}6"] = f"=SUMPRODUCT({col}3:{col}5,$E$3:$E$5)/SUM($E$3:$E$5)"
        mo[f"conclusion.{side}"] = f"Summary!{col}6"
    wsum["A6"] = "Reconciled enterprise value"

    # ── Liquidation (troubled sample: Ironvale) ──
    wl = wb.create_sheet("Liquidation")
    ti, to_ = mapping["troubled"]["inputs"], mapping["troubled"]["outputs"]
    wl["A1"], wl["A1"].font = "Liquidation and distressed going concern · Ironvale Manufacturing (MOCK) · USD millions", HEAD
    wl.append(["Asset class", "Book value", "Recovery low", "Recovery high", "Proceeds low", "Proceeds high"])
    for c in wl[2]:
        c.font = BOLD
    for k, label in (("cash", "Cash"), ("ar", "Accounts receivable"), ("inventory", "Inventory"), ("ppe", "PP&E"),
                     ("intangibles", "Intangibles"), ("other", "Other assets")):
        wl.append([label, trbl[f"book_{k}"], trbl[f"rr_{k}_low"], trbl[f"rr_{k}_high"]])
        r = wl.max_row
        for c in (2, 3, 4):
            wl.cell(r, c).fill = INPUT
        wl[f"E{r}"], wl[f"F{r}"] = f"=B{r}*C{r}", f"=B{r}*D{r}"
        ti.update({f"book_{k}": f"Liquidation!B{r}", f"rr_{k}_low": f"Liquidation!C{r}", f"rr_{k}_high": f"Liquidation!D{r}"})
    wl["A10"], wl["E10"], wl["F10"] = "Gross proceeds", "=SUM(E3:E8)", "=SUM(F3:F8)"
    wl["A11"], wl["B11"] = "Wind-down costs, % gross", trbl["wind_down_pct"]
    wl["B11"].fill = INPUT
    ti["wind_down_pct"] = "Liquidation!B11"
    wl["E11"], wl["F11"] = "=E10*$B$11", "=F10*$B$11"
    wl["A12"], wl["E12"], wl["F12"] = "Net distributable (liquidation)", "=E10-E11", "=F10-F11"
    wl["A14"], wl["B14"] = "Normalized EBITDA", trbl.get("ebitda_normalized", trbl.get("ebitda_ltm"))
    wl["A15"], wl["B15"], wl["C15"] = "Distressed EV/EBITDA (low, high)", trbl["dist_mult_low"], trbl["dist_mult_high"]
    wl["A16"], wl["B16"] = "Restructuring costs, % EV", trbl["restructuring_pct"]
    for c in ("B14", "B15", "C15", "B16"):
        wl[c].fill = INPUT
    ti.update({"ebitda_normalized": "Liquidation!B14", "dist_mult_low": "Liquidation!B15", "dist_mult_high": "Liquidation!C15",
               "restructuring_pct": "Liquidation!B16"})
    wl["A17"], wl["E17"], wl["F17"] = "Distressed EV", "=$B$14*B15", "=$B$14*C15"
    wl["A18"], wl["E18"], wl["F18"] = "Net distributable (distressed GC)", "=E17*(1-$B$16)", "=F17*(1-$B$16)"

    wl.append([])
    wl.append(["Claim", "Priority", "Amount", "Bank share", "Liq low", "Liq high", "GC low", "GC high"])
    for c in wl[wl.max_row]:
        c.font = BOLD
    first = wl.max_row + 1
    claims = tctx.capital.to_dict("records")
    last = first + len(claims) - 1
    for i, cl in enumerate(claims):
        r = first + i
        wl[f"A{r}"], wl[f"B{r}"], wl[f"C{r}"], wl[f"D{r}"] = cl["claim_class"], cl["priority"], cl["amount_musd"], cl["bank_share"]
        for c in "BCD":
            wl[f"{c}{r}"].fill = INPUT
        P, A = f"$B${first}:$B${last}", f"$C${first}:$C${last}"
        for col, net in (("E", "$E$12"), ("F", "$F$12"), ("G", "$E$18"), ("H", "$F$18")):
            level = f"SUMIF({P},B{r},{A})"
            ahead = f'SUMIF({P},"<"&B{r},{A})'
            wl[f"{col}{r}"] = f"=MIN({level},MAX(0,{net}-{ahead}))*C{r}/{level}"
        mapping["troubled"]["claims"].append({"claim_id": cl["claim_id"], "claim_class": cl["claim_class"],
                                              "priority": int(cl["priority"]), "bank_share": float(cl["bank_share"]),
                                              "amount_cell": f"Liquidation!C{r}"})
    rb = last + 2
    wl[f"A{rb}"] = "Bank recovery"
    for col, key in (("E", "liquidation.low"), ("F", "liquidation.high"), ("G", "distressed_gc.low"), ("H", "distressed_gc.high")):
        wl[f"{col}{rb}"] = f"=SUMPRODUCT({col}{first}:{col}{last},$D${first}:$D${last})"
        to_[key] = f"Liquidation!{col}{rb}"
    wl.column_dimensions["A"].width = 40

    out = ROOT / "workbook"
    out.mkdir(exist_ok=True)
    wb.save(out / "master_valuation.xlsx")
    (out / "mapping.yaml").write_text("# Cell map: engine input key / output -> workbook cell. Generated by scripts/build_mock_workbook.py\n"
                                      + yaml.safe_dump(mapping, sort_keys=False))
    print("wrote workbook/master_valuation.xlsx and workbook/mapping.yaml")


if __name__ == "__main__":
    main()
