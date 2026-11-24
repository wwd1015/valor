"""Precedent transactions: LTM EBITDA x transaction EV/EBITDA (25th / median / 75th).
Control premium is embedded in transaction multiples, so no discount is applied.
Translated from the workbook's `Precedents` sheet."""

from __future__ import annotations

from dataclasses import dataclass

from valor.engine.base import MethodResult, r2

VERSION = "precedents-1.0 (from workbook Precedents sheet)"


@dataclass
class PrecedentInputs:
    ebitda: float
    multiple_low: float
    multiple_mid: float
    multiple_high: float


def run(inp: PrecedentInputs) -> MethodResult:
    return MethodResult(
        method="precedents", label="Precedent transactions",
        low=r2(inp.ebitda * inp.multiple_low), mid=r2(inp.ebitda * inp.multiple_mid),
        high=r2(inp.ebitda * inp.multiple_high), version=VERSION,
        details={"ebitda": inp.ebitda, "multiples": [inp.multiple_low, inp.multiple_mid, inp.multiple_high]},
    )


def build_inputs(v: dict, claims: list[dict] | None = None) -> PrecedentInputs:
    return PrecedentInputs(ebitda=v["ebitda_ltm"], multiple_low=v["txn_low"], multiple_mid=v["txn_mid"],
                           multiple_high=v["txn_high"])
