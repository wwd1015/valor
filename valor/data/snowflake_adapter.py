"""PLACEHOLDER: adapter for the bank's internal Snowflake data tool (MCP-like).

To wire it up:
  1. Set `data.source: snowflake` in config/settings.yaml.
  2. Put the real physical table names in config/data_sources.yaml.
  3. Implement `_query` below with the internal tool's client. Keep the column names of the
     logical tables (see data/mock/*.csv headers); alias in SQL if the real columns differ.
Nothing else in the app changes: it only calls `DataSource.table`.
"""

from __future__ import annotations

import pandas as pd

from valor.config import table_map
from valor.data.source import DataSource


class SnowflakeToolSource(DataSource):
    name = "snowflake"
    label = "Snowflake (internal data tool)"

    def table(self, logical_name: str, **filters) -> pd.DataFrame:
        physical = table_map()[logical_name]
        where = " AND ".join(f"{col} = %({col})s" for col in filters)
        sql = f"SELECT * FROM {physical}" + (f" WHERE {where}" if where else "")
        df = self._query(sql, filters)
        df.columns = [c.lower() for c in df.columns]
        return df

    def _query(self, sql: str, params: dict) -> pd.DataFrame:  # pragma: no cover - placeholder
        # TODO(bank): call the internal data tool here, e.g.
        #   result = internal_data_tool.run_query(sql=sql, params=params)
        #   return pd.DataFrame(result.rows, columns=result.columns)
        raise NotImplementedError(
            "Snowflake adapter not wired: implement SnowflakeToolSource._query "
            "(valor/data/snowflake_adapter.py) or set data.source: mock")
