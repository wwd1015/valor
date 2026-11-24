"""Orderly-liquidation analysis: book value x recovery rate by asset class (low / high),
less wind-down costs, then the recovery waterfall. Translated from the workbook's
`Liquidation` sheet. The result measure is the bank's recovery in USD millions."""

from __future__ import annotations

from dataclasses import dataclass

from valor.engine import waterfall
from valor.engine.base import MethodResult, r2

VERSION = "liquidation-1.0 (from workbook Liquidation sheet)"

ASSET_CLASSES = [("cash", "Cash"), ("ar", "Accounts receivable"), ("inventory", "Inventory"),
                 ("ppe", "Property, plant & equipment"), ("intangibles", "Intangibles"), ("other", "Other assets")]


@dataclass
class LiquidationInputs:
    assets: list[dict]          # [{key, label, book, rr_low, rr_high}]
    wind_down_pct: float
    claims: list[dict]


def proceeds(inp: LiquidationInputs, side: str) -> dict:
    rows = [{**a, "proceeds": a["book"] * a[f"rr_{side}"]} for a in inp.assets]
    gross = sum(r["proceeds"] for r in rows)
    wind_down = gross * inp.wind_down_pct
    return {"assets": rows, "gross": gross, "wind_down": wind_down, "net": gross - wind_down}


def run(inp: LiquidationInputs) -> MethodResult:
    lo, hi = proceeds(inp, "low"), proceeds(inp, "high")
    wf_lo, wf_hi = waterfall.run(lo["net"], inp.claims), waterfall.run(hi["net"], inp.claims)
    mid = (wf_lo["bank_recovered"] + wf_hi["bank_recovered"]) / 2
    return MethodResult(
        method="liquidation", label="Liquidation analysis", measure="bank_recovery",
        low=r2(wf_lo["bank_recovered"]), mid=r2(mid), high=r2(wf_hi["bank_recovered"]), version=VERSION,
        details={
            "assets": [{"label": a["label"], "book": a["book"], "rr_low": a["rr_low"], "rr_high": a["rr_high"],
                        "proceeds_low": round(a["book"] * a["rr_low"], 4), "proceeds_high": round(a["book"] * a["rr_high"], 4)}
                       for a in inp.assets],
            "gross": {"low": r2(lo["gross"]), "high": r2(hi["gross"])},
            "wind_down": {"low": r2(lo["wind_down"]), "high": r2(hi["wind_down"])},
            "net": {"low": r2(lo["net"]), "high": r2(hi["net"])},
            "waterfall": {"low": wf_lo, "high": wf_hi},
            "value_basis": {"low": r2(lo["net"]), "mid": r2((lo["net"] + hi["net"]) / 2), "high": r2(hi["net"])},
        },
    )


def build_inputs(v: dict, claims: list[dict] | None = None) -> LiquidationInputs:
    assets = [{"key": k, "label": label, "book": v[f"book_{k}"], "rr_low": v[f"rr_{k}_low"], "rr_high": v[f"rr_{k}_high"]}
              for k, label in ASSET_CLASSES]
    return LiquidationInputs(assets=assets, wind_down_pct=v["wind_down_pct"], claims=claims_from_values(v, claims or []))


def claims_from_values(v: dict, claims: list[dict]) -> list[dict]:
    """Claim amounts are inputs (claim.<id>), so adjustments flow through the audit trail."""
    return [{"claim_id": c["claim_id"], "claim_class": c["claim_class"], "priority": int(c["priority"]),
             "amount": float(v.get(f"claim.{c['claim_id']}", c.get("amount", 0.0))), "bank_share": float(c["bank_share"])}
            for c in claims]
