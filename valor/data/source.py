"""The data-access interface. The app talks only to `DataSource`; swap the implementation in
config/settings.yaml (`data.source`). Every method returns a pandas DataFrame with the columns of
the logical table named in config/data_sources.yaml."""

from __future__ import annotations

from abc import ABC, abstractmethod
from functools import lru_cache

import pandas as pd

from valor.config import settings


class DataSource(ABC):
    name: str = "abstract"
    label: str = "Data source"

    @abstractmethod
    def table(self, logical_name: str, **filters) -> pd.DataFrame:
        """Return a logical table, optionally filtered by equality on columns."""

    # Convenience accessors built on `table`, shared by every implementation.
    def deals(self) -> pd.DataFrame:
        d = self.table("deal_facility")
        b = self.table("borrower")
        return d.merge(b, on="borrower_id", how="left")

    def deal(self, deal_id: str) -> dict:
        rows = self.deals()
        rows = rows[rows.deal_id == deal_id]
        if rows.empty:
            raise KeyError(f"deal {deal_id} not found")
        return rows.iloc[0].to_dict()

    def financials(self, borrower_id: str) -> pd.DataFrame:
        return self.table("fin_statement_annual", borrower_id=borrower_id).sort_values("fiscal_year")

    def projections(self, borrower_id: str) -> pd.DataFrame:
        return self.table("fin_projection", borrower_id=borrower_id).sort_values("year")

    def assets(self, borrower_id: str) -> pd.DataFrame:
        return self.table("balance_sheet_assets", borrower_id=borrower_id)

    def capital_structure(self, borrower_id: str) -> pd.DataFrame:
        return self.table("capital_structure", borrower_id=borrower_id).sort_values(["priority", "claim_id"])

    def first_line(self, deal_id: str) -> dict:
        rows = self.table("first_line_valuation", deal_id=deal_id)
        if rows.empty:
            return {}
        return {k: (None if pd.isna(v) else v) for k, v in rows.iloc[0].to_dict().items()}

    def ebitda_adjustments(self, borrower_id: str) -> pd.DataFrame:
        return self.table("ebitda_adjustments", borrower_id=borrower_id)

    def rates(self) -> pd.DataFrame:
        return self.table("mkt_rates")

    def sector_params(self, sector: str) -> dict:
        rows = self.table("mkt_sector_params", sector=sector)
        return rows.iloc[0].to_dict() if not rows.empty else {}

    def trading_comps(self, sector: str) -> pd.DataFrame:
        return self.table("mkt_trading_comps", sector=sector)

    def precedents(self, sector: str, distressed: bool | None = None) -> pd.DataFrame:
        t = self.table("mkt_precedent_txns", sector=sector)
        if distressed is not None:
            t = t[t.distressed.astype(str).str.lower().isin(["true", "1"]) == distressed]
        return t

    def recovery_rates(self) -> pd.DataFrame:
        return self.table("mkt_recovery_rates")


@lru_cache(maxsize=1)
def get_source() -> DataSource:
    kind = settings()["data"]["source"]
    if kind == "mock":
        from valor.data.mock import MockDataSource
        return MockDataSource()
    if kind == "snowflake":
        from valor.data.snowflake_adapter import SnowflakeToolSource
        return SnowflakeToolSource()
    raise ValueError(f"unknown data source {kind!r}")
