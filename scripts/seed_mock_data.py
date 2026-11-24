"""Generate the mock Snowflake tables in data/mock/*.csv.

Everything here is invented: borrowers, peers, transactions and rates are mock values chosen to
look plausible, not real market data. Re-run to regenerate; the output is deterministic.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "mock"
AS_OF = "2026-10-31"

BORROWERS = [
    # id, name, sector, region, internal rating, rating bucket, RM
    ("B001", "Harbor Point Logistics", "Transportation & Logistics", "Northeast", "5", "bb", "R. Alvarez"),
    ("B002", "Cedar Ridge Foods", "Food Manufacturing", "Midwest", "4", "bbb", "K. Brennan"),
    ("B003", "Bluepeak Software", "Software", "West", "5", "bb", "D. Nakamura"),
    ("B004", "Ironvale Manufacturing", "Industrial Manufacturing", "Midwest", "8", "ccc", "T. Fischer"),
    ("B005", "Meridian Retail Group", "Specialty Retail", "Southeast", "9", "ccc", "L. Moreau"),
]

# deal_id, borrower, facility name, type, lien, commitment, outstanding, status, first-line value, method, date
DEALS = [
    ("D-1001", "B001", "Senior secured term loan B", "Term loan", "First lien", 180.0, 172.0, "Performing", 610.0, "DCF and trading comps", "2026-11-03"),
    ("D-1002", "B002", "Revolver and term loan A", "Term loan", "First lien", 95.0, 81.0, "Performing", 300.0, "Trading comps", "2026-11-10"),
    ("D-1003", "B003", "Unitranche facility", "Unitranche", "First lien", 120.0, 118.0, "Performing", 420.0, "DCF", "2026-11-12"),
    ("D-2001", "B004", "ABL and term loan", "Term loan", "First lien", 140.0, 136.0, "Non-accrual", 112.0, "Liquidation analysis", "2026-11-05"),
    ("D-2002", "B005", "Senior secured ABL", "ABL", "First lien", 110.0, 104.0, "Watch list", 88.0, "Recovery waterfall", "2026-11-14"),
]

# borrower: base revenue (FY2025), margin path, d&a %, capex %, tax, total debt, cash
FIN = {
    "B001": dict(rev=[352.0, 381.0, 402.0], margin=[0.132, 0.137, 0.141], da=0.045, capex=0.050, tax=0.25, debt=236.0, cash=21.0),
    "B002": dict(rev=[231.0, 244.0, 258.0], margin=[0.118, 0.121, 0.119], da=0.035, capex=0.040, tax=0.24, debt=102.0, cash=14.0),
    "B003": dict(rev=[71.0, 83.0, 95.0], margin=[0.24, 0.26, 0.28], da=0.030, capex=0.025, tax=0.22, debt=118.0, cash=19.0),
    "B004": dict(rev=[365.0, 338.0, 309.0], margin=[0.110, 0.081, 0.058], da=0.050, capex=0.030, tax=0.21, debt=228.0, cash=6.0),
    "B005": dict(rev=[612.0, 571.0, 538.0], margin=[0.071, 0.042, 0.023], da=0.030, capex=0.015, tax=0.21, debt=196.0, cash=9.0),
}

# management projections: growth, margin for years 1-5 (optimistic on purpose, to give review something to do)
PROJ = {
    "B001": ([0.075, 0.07, 0.06, 0.05, 0.04], [0.145, 0.150, 0.153, 0.155, 0.155]),
    "B002": ([0.05, 0.045, 0.04, 0.035, 0.03], [0.121, 0.123, 0.124, 0.125, 0.125]),
    "B003": ([0.16, 0.14, 0.12, 0.10, 0.08], [0.29, 0.31, 0.33, 0.34, 0.35]),
    "B004": ([-0.03, 0.02, 0.03, 0.03, 0.03], [0.060, 0.070, 0.080, 0.085, 0.090]),
    "B005": ([-0.04, -0.01, 0.01, 0.02, 0.02], [0.025, 0.035, 0.045, 0.050, 0.050]),
}

ASSETS = {
    "B004": dict(cash=6.0, accounts_receivable=48.0, inventory=71.0, ppe=118.0, intangibles=34.0, other=9.0),
    "B005": dict(cash=9.0, accounts_receivable=18.0, inventory=121.0, ppe=46.0, intangibles=22.0, other=7.0),
    "B001": dict(cash=21.0, accounts_receivable=52.0, inventory=6.0, ppe=210.0, intangibles=40.0, other=11.0),
    "B002": dict(cash=14.0, accounts_receivable=29.0, inventory=34.0, ppe=88.0, intangibles=25.0, other=5.0),
    "B003": dict(cash=19.0, accounts_receivable=17.0, inventory=0.0, ppe=6.0, intangibles=61.0, other=4.0),
}

# claim_id, class, priority (1 = first paid), amount, bank share of the class, secured
CAPITAL = {
    "B001": [("C1", "First-lien term loan B", 2, 172.0, 1.0, True), ("C2", "Senior unsecured notes", 3, 64.0, 0.0, False)],
    "B002": [("C1", "First-lien revolver and TLA", 2, 81.0, 1.0, True), ("C2", "Subordinated notes", 3, 21.0, 0.0, False)],
    "B003": [("C1", "Unitranche", 2, 118.0, 1.0, True)],
    "B004": [
        ("C0", "Administrative and professional fees", 1, 9.0, 0.0, False),
        ("C1", "First-lien ABL and term loan", 2, 136.0, 1.0, True),
        ("C2", "Second-lien notes", 3, 62.0, 0.0, True),
        ("C3", "Trade payables and general unsecured", 4, 54.0, 0.0, False),
        ("C4", "Pension shortfall (unsecured)", 4, 21.0, 0.0, False),
    ],
    "B005": [
        ("C0", "Administrative and professional fees", 1, 7.0, 0.0, False),
        ("C1", "Priority tax and wage claims", 1, 5.0, 0.0, False),
        ("C2", "Senior secured ABL", 2, 104.0, 1.0, True),
        ("C3", "Term loan (second lien)", 3, 85.0, 0.0, True),
        ("C4", "Landlord and trade claims", 4, 96.0, 0.0, False),
    ],
}

# Review trigger, due date and the loan's effective interest rate (for discounting recoveries).
DEAL_EXTRA = {
    "D-1001": ("Annual review", "2026-12-05", 0.085),
    "D-1002": ("New origination", "2026-12-12", 0.072),
    "D-1003": ("Amendment: incremental term loan", "2026-12-01", 0.095),
    "D-2001": ("Workout: impairment assessment", "2026-11-28", 0.110),
    "D-2002": ("Watch-list review", "2026-12-10", 0.105),
}

# The first line's valuation package: the assumptions behind its number (what the second line challenges).
# deal: method, value, EBITDA used, multiple used, WACC, terminal growth, year-1 growth, recovery %, prepared by, date
FIRST_LINE = {
    "D-1001": ("DCF and trading comps", 610.0, 70.4, 9.5, 0.090, 0.030, 0.075, None, "Leveraged Finance deal team", "2026-10-28"),
    "D-1002": ("Trading comps", 300.0, 34.6, 8.7, 0.085, 0.025, 0.050, None, "Corporate Banking deal team", "2026-11-04"),
    "D-1003": ("DCF", 420.0, 32.9, 12.8, 0.110, 0.030, 0.160, None, "Technology Finance deal team", "2026-11-06"),
    "D-2001": ("Liquidation analysis", 112.0, 24.9, 5.0, None, None, None, 0.82, "Special Assets Group", "2026-10-30"),
    "D-2002": ("Recovery waterfall", 88.0, 18.0, 4.5, None, None, None, 0.85, "Special Assets Group", "2026-11-07"),
}

# Management / sponsor EBITDA add-backs (the "adjusted EBITDA" bridge the first line relied on).
# borrower: (id, description, category, amount, support)
ADDBACKS = {
    "B001": [("A1", "Depot network restructuring (one-time)", "restructuring", 4.2, "QoE verified"),
             ("A2", "Run-rate fuel-surcharge pricing", "pro_forma", 3.5, "Management estimate"),
             ("A3", "Sponsor monitoring fees", "owner_related", 1.0, "Audited"),
             ("A4", "CrossDock acquisition synergies (expected)", "synergies", 5.0, "Management estimate")],
    "B002": [("A1", "Product recall (one-time)", "restructuring", 2.1, "QoE verified"),
             ("A2", "Plant consolidation savings (run-rate)", "pro_forma", 1.8, "Management estimate")],
    "B003": [("A1", "Stock-based compensation (non-cash)", "non_cash", 3.8, "Audited"),
             ("A2", "Annualized new contract wins", "pro_forma", 2.5, "Management estimate")],
    "B004": [("A1", "Plant closure costs", "restructuring", 3.0, "QoE verified"),
             ("A2", "Expected customer re-win", "pro_forma", 4.0, "Management estimate")],
    "B005": [("A1", "Store closure costs", "restructuring", 2.6, "QoE verified"),
             ("A2", "Rent renegotiation savings (run-rate)", "pro_forma", 3.0, "Management estimate")],
}

RATES = [
    ("ust_10y", 0.0425), ("equity_risk_premium", 0.055), ("long_term_growth", 0.025),
    ("cost_of_debt_bbb", 0.062), ("cost_of_debt_bb", 0.074), ("cost_of_debt_b", 0.089), ("cost_of_debt_ccc", 0.125),
]

SECTORS = [
    # sector, unlevered beta, size premium, target D/cap
    ("Transportation & Logistics", 0.92, 0.015, 0.35),
    ("Food Manufacturing", 0.68, 0.015, 0.30),
    ("Software", 1.15, 0.020, 0.15),
    ("Industrial Manufacturing", 0.98, 0.020, 0.30),
    ("Specialty Retail", 1.05, 0.020, 0.30),
]

COMPS_CENTER = {  # sector: (EV/EBITDA centre, EV/Revenue centre)
    "Transportation & Logistics": (9.0, 1.3),
    "Food Manufacturing": (10.5, 1.2),
    "Software": (17.0, 5.0),
    "Industrial Manufacturing": (8.0, 1.0),
    "Specialty Retail": (6.5, 0.5),
}

RECOVERY = [
    ("cash", 1.00, 1.00), ("accounts_receivable", 0.70, 0.85), ("inventory", 0.40, 0.65),
    ("ppe", 0.35, 0.60), ("intangibles", 0.00, 0.15), ("other", 0.10, 0.30),
]


def write(name: str, header: list[str], rows: list[tuple]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / f"{name}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main() -> None:
    rnd = random.Random(20261124)
    write("borrower", ["borrower_id", "borrower_name", "sector", "region", "internal_rating", "rating_bucket", "relationship_manager"], BORROWERS)
    write("deal_facility", ["deal_id", "borrower_id", "facility_name", "facility_type", "lien_position", "commitment_musd",
                            "outstanding_musd", "risk_status", "first_line_value_musd", "first_line_method", "request_date",
                            "request_type", "review_due", "effective_rate"],
          [(*d, *DEAL_EXTRA[d[0]]) for d in DEALS])
    write("first_line_valuation", ["deal_id", "primary_method", "value_musd", "ebitda_used", "multiple_used", "wacc",
                                   "terminal_growth", "growth_y1", "recovery_pct", "prepared_by", "valuation_date"],
          [(d, *v) for d, v in FIRST_LINE.items()])
    write("ebitda_adjustments", ["borrower_id", "adj_id", "description", "category", "amount_musd", "support"],
          [(b, *a) for b, adds in ADDBACKS.items() for a in adds])

    fin_rows = []
    for b, f in FIN.items():
        for i, year in enumerate([2023, 2024, 2025]):
            rev = f["rev"][i]
            ebitda = round(rev * f["margin"][i], 2)
            prev = f["rev"][i - 1] if i else rev / 1.05
            fin_rows.append((b, year, rev, ebitda, round(rev * f["da"], 2), round(rev * f["capex"], 2),
                             round((rev - prev) * 0.10, 2), f["tax"], f["debt"], f["cash"]))
    write("fin_statement_annual", ["borrower_id", "fiscal_year", "revenue", "ebitda", "d_and_a", "capex", "change_nwc",
                                   "tax_rate", "total_debt", "cash"], fin_rows)

    write("fin_projection", ["borrower_id", "year", "revenue_growth", "ebitda_margin", "case"],
          [(b, y + 1, g[y], m[y], "Management") for b, (g, m) in PROJ.items() for y in range(5)])
    write("balance_sheet_assets", ["borrower_id", "asset_class", "book_value", "as_of"],
          [(b, k, v, "2026-09-30") for b, a in ASSETS.items() for k, v in a.items()])
    write("capital_structure", ["borrower_id", "claim_id", "claim_class", "priority", "amount_musd", "bank_share", "secured"],
          [(b, *c) for b, cs in CAPITAL.items() for c in cs])
    write("mkt_rates", ["as_of", "metric", "value", "vendor_field"], [(AS_OF, m, v, f"PLACEHOLDER.{m.upper()}") for m, v in RATES])
    write("mkt_sector_params", ["sector", "unlevered_beta", "size_premium", "target_debt_to_cap", "as_of"],
          [(*s, AS_OF) for s in SECTORS])

    comps, txns = [], []
    for sector, (c_ebitda, c_rev) in COMPS_CENTER.items():
        code = "".join(w[0] for w in sector.replace("&", "").split())
        for i in range(7):
            m = round(c_ebitda * rnd.uniform(0.75, 1.3), 1)
            comps.append((sector, f"{code}{i + 1}", f"{sector.split()[0]} Peer {chr(65 + i)} (mock)",
                          m, round(c_rev * m / c_ebitda * rnd.uniform(0.9, 1.1), 2), AS_OF))
        for i in range(6):
            m = round(c_ebitda * rnd.uniform(0.9, 1.45), 1)
            ev = round(rnd.uniform(150, 900), 0)
            txns.append((sector, f"202{rnd.randint(1, 6)}-{rnd.randint(1, 12):02d}-15", f"{code} Target {i + 1} (mock)",
                         f"Acquirer {chr(80 + i)} (mock)", ev, m, round(c_rev * m / c_ebitda, 2), False))
        for i in range(4):
            m = round(c_ebitda * rnd.uniform(0.45, 0.7), 1)
            ev = round(rnd.uniform(60, 300), 0)
            txns.append((sector, f"202{rnd.randint(1, 6)}-{rnd.randint(1, 12):02d}-01", f"{code} Distressed {i + 1} (mock)",
                         f"Buyer {chr(70 + i)} (mock)", ev, m, round(c_rev * m / c_ebitda, 2), True))
    write("mkt_trading_comps", ["sector", "ticker", "company_name", "ev_ebitda", "ev_revenue", "as_of"], comps)
    write("mkt_precedent_txns", ["sector", "close_date", "target", "acquirer", "ev_musd", "ev_ebitda", "ev_revenue", "distressed"], txns)
    write("mkt_recovery_rates", ["asset_class", "recovery_low", "recovery_high", "as_of"], [(*r, AS_OF) for r in RECOVERY])
    print(f"wrote mock tables to {OUT}")


if __name__ == "__main__":
    main()
