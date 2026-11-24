"""Mock Snowflake: reads placeholder tables from data/mock/<logical_name>.csv.
Regenerate with `python scripts/seed_mock_data.py`, or replace the CSVs with extracts."""

from __future__ import annotations

from functools import lru_cache

import pandas as pd

from valor.config import MOCK_DATA_DIR, table_map
from valor.data.source import DataSource


@lru_cache(maxsize=None)
def _read(name: str) -> pd.DataFrame:
    return pd.read_csv(MOCK_DATA_DIR / f"{name}.csv")


class MockDataSource(DataSource):
    name = "mock"
    label = "Mock Snowflake (data/mock)"

    def table(self, logical_name: str, **filters) -> pd.DataFrame:
        if logical_name not in table_map():
            raise KeyError(f"unknown table {logical_name!r}; add it to config/data_sources.yaml")
        df = _read(logical_name).copy()
        for col, val in filters.items():
            df = df[df[col] == val]
        return df.reset_index(drop=True)

    def physical_name(self, logical_name: str) -> str:
        return table_map()[logical_name]
