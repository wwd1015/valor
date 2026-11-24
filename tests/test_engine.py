"""Unit tests for each valuation method, on hand-checkable numbers."""

import pytest

from valor.engine import comps, dcf, distressed, liquidation, precedents, reconcile, waterfall
from valor.engine.base import MethodResult


def test_wacc_relevering():
    w = dcf.wacc(dcf.WACCInputs(risk_free=0.04, erp=0.05, beta_unlevered=1.0, size_premium=0.0, debt_to_cap=0.5,
                                cost_of_debt=0.08, tax_rate=0.25))
    assert w["levered_beta"] == pytest.approx(1.75)            # 1 * (1 + 0.75 * 1)
    assert w["cost_of_equity"] == pytest.approx(0.1275)
    assert w["wacc"] == pytest.approx(0.5 * 0.1275 + 0.5 * 0.06)


def test_dcf_flat_perpetuity_matches_gordon():
    # No growth, no reinvestment: EV = FCF / WACC
    inp = dcf.DCFInputs(base_revenue=100, growth=[0] * 5, margin=[0.2] * 5, da_pct_rev=0, capex_pct_rev=0,
                        nwc_pct_incr_rev=0, tax_rate=0.25,
                        wacc=dcf.WACCInputs(0.10, 0.0, 0.0, 0.0, 0.0, 0.0, 0.25), terminal_growth=0.0)
    r = dcf.run(inp)
    assert r.mid == pytest.approx(15 / 0.10, abs=0.01)
    assert r.low < r.mid < r.high


def test_dcf_rejects_growth_above_wacc():
    inp = dcf.DCFInputs(100, [0] * 5, [0.2] * 5, 0, 0, 0, 0.25, dcf.WACCInputs(0.03, 0, 0, 0, 0, 0, 0.25), 0.04)
    with pytest.raises(ValueError):
        dcf.run(inp)


def test_comps_and_precedents():
    c = comps.run(comps.CompsInputs(ebitda=10, multiple_low=6, multiple_mid=8, multiple_high=10, private_discount=0.1))
    assert (c.low, c.mid, c.high) == (54.0, 72.0, 90.0)
    p = precedents.run(precedents.PrecedentInputs(ebitda=10, multiple_low=7, multiple_mid=9, multiple_high=11))
    assert (p.low, p.mid, p.high) == (70.0, 90.0, 110.0)


CLAIMS = [{"claim_id": "A", "claim_class": "Admin", "priority": 1, "amount": 10, "bank_share": 0},
          {"claim_id": "B", "claim_class": "Bank 1L", "priority": 2, "amount": 100, "bank_share": 1},
          {"claim_id": "C", "claim_class": "Trade", "priority": 3, "amount": 30, "bank_share": 0},
          {"claim_id": "D", "claim_class": "Pension", "priority": 3, "amount": 10, "bank_share": 0}]


def test_waterfall_absolute_priority_and_pro_rata():
    w = waterfall.run(130, CLAIMS)
    rec = {c["claim_id"]: c["recovered"] for c in w["claims"]}
    assert rec == {"A": 10, "B": 100, "C": 15, "D": 5}          # 20 left for class 3, shared 30:10
    assert w["bank_recovery_pct"] == 1.0
    short = waterfall.run(60, CLAIMS)
    assert short["bank_recovered"] == 50 and short["bank_recovery_pct"] == 0.5
    assert waterfall.run(-5, CLAIMS)["bank_recovered"] == 0


def test_liquidation_and_distressed():
    assets = [{"key": "inv", "label": "Inventory", "book": 100, "rr_low": 0.4, "rr_high": 0.6}]
    liq = liquidation.run(liquidation.LiquidationInputs(assets=assets, wind_down_pct=0.1, claims=CLAIMS))
    # net low = 40*0.9 = 36 -> bank gets 26; high = 54 -> 44
    assert (liq.low, liq.high, liq.mid) == (26.0, 44.0, 35.0)
    d = distressed.run(distressed.DistressedInputs(ebitda=20, multiple_low=4, multiple_high=6, restructuring_pct=0.05, claims=CLAIMS))
    assert d.low == pytest.approx(66.0)                          # 80 * .95 = 76 - 10 admin
    assert d.high == pytest.approx(100.0)


def test_reconcile_weights_and_metrics():
    t = {"conclusion": "enterprise_value", "methods": [{"id": "a", "weight_input": "wa"}, {"id": "b", "weight_input": "wb"}]}
    res = [MethodResult("a", "A", 100, 200, 300), MethodResult("b", "B", 200, 400, 600)]
    v = {"wa": 0.5, "wb": 0.5, "first_line_value": 250, "bank_exposure": 100, "debt_ahead": 50}
    c = reconcile(t, v, res, 0.15)
    assert (c["low"], c["mid"], c["high"]) == (150, 300, 450)
    assert c["vs_first_line"] == pytest.approx(0.2) and c["variance_flag"]
    assert c["ltv_mid"] == pytest.approx(0.5) and c["coverage_mid"] == pytest.approx(2.5)
    v.update(wa=0.6, wb=0.6)
    assert reconcile(t, v, res, 0.15)["weights_normalized"]
