"""Trading comparables: LTM EBITDA x peer EV/EBITDA (25th / median / 75th), less a
private-company discount. Translated from the workbook's `Comps` sheet."""

from __future__ import annotations

from dataclasses import dataclass

from valor.engine.base import MethodResult, r2

VERSION = "comps-1.0 (from workbook Comps sheet)"


@dataclass
class CompsInputs:
    ebitda: float
    multiple_low: float
    multiple_mid: float
    multiple_high: float
    private_discount: float


def run(inp: CompsInputs) -> MethodResult:
    f = inp.ebitda * (1 - inp.private_discount)
    return MethodResult(
        method="trading_comps", label="Trading comparables",
        low=r2(f * inp.multiple_low), mid=r2(f * inp.multiple_mid), high=r2(f * inp.multiple_high),
        version=VERSION,
        details={"ebitda": inp.ebitda, "multiples": [inp.multiple_low, inp.multiple_mid, inp.multiple_high],
                 "private_discount": inp.private_discount},
    )


def build_inputs(v: dict, claims: list[dict] | None = None) -> CompsInputs:
    return CompsInputs(ebitda=v["ebitda_ltm"], multiple_low=v["comps_low"], multiple_mid=v["comps_mid"],
                       multiple_high=v["comps_high"], private_discount=v["private_discount"])
