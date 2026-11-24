"""The engine must reproduce the master workbook's own outputs (recalculated from its formulas)."""

import pytest

from valor.engine import reconcile, run_methods
from valor.excel import workbook
from valor.workflow import template


@pytest.mark.parametrize("method", ["dcf", "trading_comps", "precedents", "liquidation", "distressed_gc"])
def test_method_matches_workbook(method):
    res = workbook.parity(method)
    assert res["rows"], f"no outputs mapped for {method}"
    assert res["ok"], res["rows"]


def test_reconciled_value_matches_workbook_summary():
    case = workbook.workbook_cases()["performing"]
    t = template("performing")
    results = run_methods(t, case["values"], case["claims"])
    c = reconcile(t, case["values"], results, 0.15)
    for side in ("low", "mid", "high"):
        assert c[side] == pytest.approx(case["expected"][f"conclusion.{side}"], abs=0.02)
