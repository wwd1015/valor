"""Distressed going-concern valuation: normalized EBITDA x distressed EV/EBITDA (low / high),
less restructuring costs, then the recovery waterfall. Measure: bank recovery, USD millions."""

from __future__ import annotations

from dataclasses import dataclass

from valor.engine import waterfall
from valor.engine.base import MethodResult, r2
from valor.engine.liquidation import claims_from_values

VERSION = "distressed-1.0 (from workbook Liquidation sheet, distressed GC block)"


@dataclass
class DistressedInputs:
    ebitda: float
    multiple_low: float
    multiple_high: float
    restructuring_pct: float
    claims: list[dict]


def run(inp: DistressedInputs) -> MethodResult:
    out = {}
    for side, m in (("low", inp.multiple_low), ("high", inp.multiple_high)):
        ev = inp.ebitda * m
        costs = ev * inp.restructuring_pct
        out[side] = {"ev": ev, "restructuring": costs, "distributable": ev - costs,
                     "waterfall": waterfall.run(ev - costs, inp.claims)}
    lo, hi = out["low"]["waterfall"]["bank_recovered"], out["high"]["waterfall"]["bank_recovered"]
    return MethodResult(
        method="distressed_gc", label="Distressed going concern", measure="bank_recovery",
        low=r2(lo), mid=r2((lo + hi) / 2), high=r2(hi), version=VERSION,
        details={
            "ebitda": inp.ebitda, "multiples": [inp.multiple_low, inp.multiple_high],
            "ev": {s: r2(out[s]["ev"]) for s in out},
            "restructuring": {s: r2(out[s]["restructuring"]) for s in out},
            "distributable": {s: r2(out[s]["distributable"]) for s in out},
            "waterfall": {s: out[s]["waterfall"] for s in out},
            "value_basis": {"low": r2(out["low"]["distributable"]),
                            "mid": r2((out["low"]["distributable"] + out["high"]["distributable"]) / 2),
                            "high": r2(out["high"]["distributable"])},
        },
    )


def build_inputs(v: dict, claims: list[dict] | None = None) -> DistressedInputs:
    return DistressedInputs(ebitda=v["ebitda_normalized"], multiple_low=v["dist_mult_low"],
                            multiple_high=v["dist_mult_high"], restructuring_pct=v["restructuring_pct"],
                            claims=claims_from_values(v, claims or []))
