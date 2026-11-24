"""Resolve a workflow input's `source` string to a value and a human-readable provenance.

Source syntax is documented at the top of config/workflows/performing.yaml. Add a resolver
here to support a new kind of source."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from valor.data.source import DataSource


@dataclass
class Resolved:
    value: float | None
    ref: str          # e.g. "FIN_STATEMENT_ANNUAL.revenue (FY2025)"
    note: str = ""


class PullContext:
    """All data for one deal, pulled once and reused by every resolver."""

    def __init__(self, src: DataSource, deal_id: str):
        self.src = src
        self.deal = src.deal(deal_id)
        bid = self.deal["borrower_id"]
        self.sector = self.deal["sector"]
        self.fin = src.financials(bid)
        self.proj = src.projections(bid)
        self.assets = src.assets(bid)
        self.capital = src.capital_structure(bid)
        self.rates = src.rates()
        self.sector_params = src.sector_params(self.sector)
        self.comps = src.trading_comps(self.sector)
        self.txns = src.precedents(self.sector, distressed=False)
        self.txns_distressed = src.precedents(self.sector, distressed=True)
        self.recovery = src.recovery_rates()
        self.first_line = src.first_line(deal_id)
        self.addbacks = src.ebitda_adjustments(bid)

    def tables(self) -> dict[str, pd.DataFrame]:
        return {"financials": self.fin, "projections": self.proj, "assets": self.assets,
                "capital_structure": self.capital, "rates": self.rates, "trading_comps": self.comps,
                "precedent_transactions": self.txns, "distressed_transactions": self.txns_distressed,
                "recovery_rates": self.recovery,
                "ebitda_adjustments": self.addbacks}


STATS = {"p25": lambda s: s.quantile(0.25), "median": lambda s: s.median(), "p75": lambda s: s.quantile(0.75),
         "mean": lambda s: s.mean()}


def _r(x) -> float:
    return round(float(x), 6)


def resolve(source: str, ctx: PullContext) -> Resolved:
    kind, _, rest = source.partition(":")
    args = rest.split(":") if rest else []
    latest = ctx.fin.iloc[-1] if not ctx.fin.empty else None

    if kind == "const":
        return Resolved(_r(args[0]), "Template default")
    if kind == "fin":
        return Resolved(_r(latest[args[0]]), f"FIN_STATEMENT_ANNUAL.{args[0]} (FY{int(latest.fiscal_year)})")
    if kind == "fin_ratio":
        num, den = args
        return Resolved(_r(latest[num] / latest[den]), f"FIN_STATEMENT_ANNUAL.{num} / {den} (FY{int(latest.fiscal_year)})")
    if kind == "proj":
        col, year = args[0], int(args[1])
        row = ctx.proj[ctx.proj.year == year]
        return Resolved(_r(row.iloc[0][col]) if not row.empty else None, f"FIN_PROJECTION.{col} (year {year}, management case)")
    if kind == "rate":
        row = ctx.rates[ctx.rates.metric == args[0]]
        return Resolved(_r(row.iloc[0].value), f"MKT_RATES.{args[0]} (as of {row.iloc[0].as_of})")
    if kind == "credit_rate":
        metric = f"{args[0]}_{ctx.deal['rating_bucket']}"
        row = ctx.rates[ctx.rates.metric == metric]
        return Resolved(_r(row.iloc[0].value), f"MKT_RATES.{metric} (rating bucket {str(ctx.deal['rating_bucket']).upper()})")
    if kind == "sector":
        return Resolved(_r(ctx.sector_params[args[0]]), f"MKT_SECTOR_PARAMS.{args[0]} ({ctx.sector})")
    if kind in ("comps", "txn", "txn_distressed"):
        col, stat = args
        df = {"comps": ctx.comps, "txn": ctx.txns, "txn_distressed": ctx.txns_distressed}[kind]
        table = {"comps": "MKT_TRADING_COMPS", "txn": "MKT_PRECEDENT_TRANSACTIONS",
                 "txn_distressed": "MKT_PRECEDENT_TRANSACTIONS[distressed]"}[kind]
        if df.empty:
            return Resolved(None, f"{table}.{col}", "no observations for sector")
        return Resolved(round(float(STATS[stat](df[col])), 2), f"{table}.{col} {stat} (n={len(df)}, {ctx.sector})")
    if kind == "deal":
        return Resolved(_r(ctx.deal[args[0]]), f"DEAL_FACILITY.{args[0]} ({ctx.deal['deal_id']})")
    if kind == "asset":
        row = ctx.assets[ctx.assets.asset_class == args[0]]
        return Resolved(_r(row.iloc[0].book_value) if not row.empty else 0.0,
                        f"BALANCE_SHEET_ASSETS.{args[0]} (as of {row.iloc[0].as_of if not row.empty else 'n/a'})")
    if kind == "recovery":
        cls, side = args
        row = ctx.recovery[ctx.recovery.asset_class == cls]
        return Resolved(_r(row.iloc[0][f"recovery_{side}"]), f"MKT_RECOVERY_RATES.{cls} {side}")
    if kind == "debt_ahead":
        bank_rows = ctx.capital[ctx.capital.bank_share > 0]
        if bank_rows.empty:
            return Resolved(0.0, "CAPITAL_STRUCTURE (no bank claim found)")
        bank_priority = bank_rows.priority.min()
        ahead = ctx.capital[ctx.capital.priority < bank_priority].amount_musd.sum()
        return Resolved(_r(ahead), f"CAPITAL_STRUCTURE claims with priority < {int(bank_priority)}")
    raise ValueError(f"unknown source kind {kind!r} in {source!r}")
