"""Valuation engine entry point: run the methods a workflow requires, reconcile them, and add the
second-line review analytics (earnings bridge, downside, reserve, policy, first-line comparison)."""

from __future__ import annotations

import importlib
from types import ModuleType

from valor.config import engine_registry
from valor.engine import review
from valor.engine.base import MethodResult, r2


def method_module(method_id: str) -> ModuleType:
    spec = engine_registry()[method_id]
    return importlib.import_module(spec["module"])


def run_methods(template: dict, values: dict, claims: list[dict]) -> list[MethodResult]:
    results = []
    sens = template.get("sensitivity", {})
    for m in template["methods"]:
        mod = method_module(m["id"])
        if m["id"] == "dcf":
            inp = mod.build_inputs(values, claims, wacc_step=sens.get("wacc_step", 0.01),
                                   growth_step=sens.get("growth_step", 0.005))
        else:
            inp = mod.build_inputs(values, claims)
        res = mod.run(inp)
        res.details["weight"] = values.get(m["weight_input"], 0.0)
        results.append(res)
    return results


def reconcile(template: dict, values: dict, results: list[MethodResult], variance_flag: float) -> dict:
    weights = {r.method: values.get(m["weight_input"], 0.0) for r, m in zip(results, template["methods"])}
    total_w = sum(weights.values())
    norm = {k: (w / total_w if total_w else 1 / len(weights)) for k, w in weights.items()}
    concl = {side: r2(sum(getattr(r, side) * norm[r.method] for r in results)) for side in ("low", "mid", "high")}
    out = {"measure": template["conclusion"], "weights": weights, "weights_total": round(total_w, 6),
           "weights_normalized": total_w and abs(total_w - 1) > 1e-6, **concl}

    first = values.get("first_line_value") or 0.0
    out["first_line_value"] = first
    out["vs_first_line"] = round((concl["mid"] - first) / first, 4) if first else None
    out["variance_flag"] = out["vs_first_line"] is not None and abs(out["vs_first_line"]) > variance_flag

    exposure = values.get("bank_exposure") or 0.0
    out["bank_exposure"] = exposure
    if template["conclusion"] == "enterprise_value":
        ahead = values.get("debt_ahead", 0.0)
        out["debt_ahead"] = ahead
        for side in ("low", "mid", "high"):
            ev = concl[side]
            out[f"ltv_{side}"] = round((ahead + exposure) / ev, 4) if ev else None
            out[f"coverage_{side}"] = round((ev - ahead) / exposure, 4) if exposure else None
    else:
        for side in ("low", "mid", "high"):
            out[f"recovery_pct_{side}"] = round(concl[side] / exposure, 4) if exposure else None
    return out


def run_valuation(template: dict, values: dict, claims: list[dict], variance_flag: float = 0.15,
                  extras: dict | None = None, policy: dict | None = None) -> dict:
    extras = extras or {}
    policy = policy or {"rag_green": 0.05, "rag_amber": 0.15, "max_ltv": 0.6, "max_ltv_downside": 0.75, "min_coverage": 1.5}
    bridge = review.earnings_bridge(values, extras.get("addbacks", []))
    eff = review.effective_values(values, bridge)
    results = run_methods(template, eff, claims)
    conclusion = reconcile(template, eff, results, variance_flag)
    conclusion["rag"] = review.rag(conclusion["vs_first_line"], policy)

    downside = None
    if template["conclusion"] == "enterprise_value" and "stress_ebitda" in values:
        s = review.stressed_values(eff)
        d_results = run_methods(template, s, claims)
        downside = reconcile(template, s, d_results, variance_flag)
        downside["methods"] = [{"method": r.method, "label": r.label, "low": r.low, "mid": r.mid, "high": r.high}
                               for r in d_results]
        downside["shocks"] = {k: values.get(k) for k in ("stress_ebitda", "stress_multiple", "stress_wacc")}
    res_reserve = review.reserve(conclusion, eff) if template["conclusion"] == "bank_recovery" else None
    tests = review.policy_tests(conclusion, downside, policy)
    method_map = {r.method: r.to_dict() for r in results}
    comparison = review.first_line_comparison(extras.get("first_line", {}), eff, bridge, method_map, conclusion, policy)
    return {"methods": [r.to_dict() for r in results], "conclusion": conclusion, "earnings": bridge,
            "downside": downside, "reserve": res_reserve, "policy_tests": tests, "first_line_comparison": comparison}
