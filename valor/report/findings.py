"""Structured findings: the single source every report template renders from.
Same numbers, any format."""

from __future__ import annotations

import hashlib
import json

from valor import service, store
from valor.config import settings, user
from valor.fmt import fmt, money, pct
from valor.workflow import template

MEASURE_LABEL = {"enterprise_value": "Enterprise value", "bank_recovery": "Bank recovery"}


def build(case_id: str, actor: str) -> dict:
    case = service.get_case(case_id)
    run = service.latest_run(case_id)
    if not run:
        raise service.ReviewError("Run the valuation before generating a report.")
    t = template(case["workflow"])
    d = case["deal"]
    res = run["results"]
    c = res["conclusion"]
    inputs = service.get_inputs(case_id)
    groups = {g["id"]: g["label"] for g in t["input_groups"]}

    deal = {"case_id": case_id, "borrower": case["borrower_name"], "sector": case["sector"],
            "facility": d.get("facility_name"), "facility_type": d.get("facility_type"), "lien": d.get("lien_position"),
            "risk_status": d.get("risk_status"), "commitment": money(d.get("commitment_musd")),
            "outstanding": money(d.get("outstanding_musd")), "request_date": d.get("request_date"),
            "relationship_manager": d.get("relationship_manager"), "internal_rating": d.get("internal_rating"),
            "first_line_method": d.get("first_line_method"), "deal_id": case["deal_id"]}

    results = []
    for m in res["methods"]:
        results.append({"method": m["method"], "label": m["label"], "low": money(m["low"]), "mid": money(m["mid"]),
                        "high": money(m["high"]), "weight": pct(m["details"].get("weight")),
                        "measure": MEASURE_LABEL[m["measure"]], "version": m["version"],
                        "raw": {"low": m["low"], "mid": m["mid"], "high": m["high"]}})

    measure = MEASURE_LABEL[c["measure"]]
    concl = {"measure": c["measure"], "measure_label": measure, "low": money(c["low"]), "mid": money(c["mid"]),
             "high": money(c["high"]), "first_line_value": money(c["first_line_value"]),
             "vs_first_line": pct(c["vs_first_line"], signed=True), "variance_flag": c["variance_flag"],
             "bank_exposure": money(c["bank_exposure"]),
             "raw": {k: v for k, v in c.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}}
    if c["measure"] == "enterprise_value":
        concl.update(ltv=pct(c.get("ltv_mid")), coverage=f"{c['coverage_mid']:.2f}x" if c.get("coverage_mid") else "—",
                     debt_ahead=money(c.get("debt_ahead")))
        concl["statement"] = (f"Second-line enterprise value of {concl['mid']} (range {concl['low']} to {concl['high']}), "
                              f"{concl['vs_first_line']} versus the first line's {concl['first_line_value']}. "
                              f"Loan-to-value at the midpoint is {concl['ltv']}, and value after senior debt covers the "
                              f"bank's {concl['bank_exposure']} commitment {concl['coverage']}.")
    else:
        concl.update(recovery_pct=pct(c.get("recovery_pct_mid")), recovery_pct_low=pct(c.get("recovery_pct_low")),
                     recovery_pct_high=pct(c.get("recovery_pct_high")))
        concl["statement"] = (f"Estimated recovery on the bank's {concl['bank_exposure']} exposure of {concl['mid']} "
                              f"({concl['recovery_pct']}), range {concl['low']} to {concl['high']}, "
                              f"{concl['vs_first_line']} versus the first line's {concl['first_line_value']}.")

    key_inputs = [{"group": groups.get(i["grp"], i["grp"]), "label": i["label"], "value": fmt(i["value"], i["unit"]),
                   "source_value": fmt(i["source_value"], i["unit"]), "source": i["source_ref"],
                   "adjusted": i["value"] != i["source_value"]} for i in inputs]

    adjustments = [{"label": a["label"], "from": fmt(a["source_value"], a["unit"]), "to": fmt(a["value"], a["unit"]),
                    "rationale": a["rationale"] or "", "by": user(a["actor"])["name"] if a["actor"] else "",
                    "when": (a["ts"] or "")[:10], "via_agent": a["via_agent"]} for a in service.adjustments(case_id)]

    labels = {i["key"]: (i["label"], i["unit"]) for i in inputs}
    recs = []
    for r in service.recommendations(case_id):
        lab, unit = labels.get(r["field"], (None, "musd"))
        recs.append({"title": r["title"], "severity": r["severity"], "status": r["status"], "field": lab,
                     "current": fmt(r["current_value"], unit) if r["field"] else "",
                     "proposed": fmt(r["proposed_value"], unit) if r["proposed_value"] is not None else "",
                     "final": fmt(r["final_value"], unit) if r["final_value"] is not None else "",
                     "rationale": r["rationale"], "decided_by": user(r["decided_by"])["name"] if r["decided_by"] else "",
                     "note": r["decision_note"] or "", "source": r["source"]})

    approvals = [{"action": {"submit": "Submitted", "send_back": "Sent back", "approve": "Approved"}[r["action"]],
                  "by": user(r["actor"])["name"], "role": user(r["actor"])["title"], "when": r["ts"][:16].replace("T", " "),
                  "comment": r["comment"] or ""} for r in service.reviews(case_id)]

    waterfall = []
    mres = {m["method"]: m for m in res["methods"]}
    if c["measure"] == "bank_recovery":
        for side in ("low", "high"):
            for mid_, m in mres.items():
                wf = m["details"]["waterfall"][side]
                for cl in wf["claims"]:
                    waterfall.append({"scenario": f"{m['label']}, {side}", "claim": cl["claim_class"],
                                      "priority": cl["priority"], "claim_amount": money(cl["amount"]),
                                      "recovered": money(cl["recovered"]), "recovery_pct": pct(cl["recovery_pct"]),
                                      "bank": cl["bank_share"] > 0})

    dcf = None
    if "dcf" in mres:
        dd = mres["dcf"]["details"]
        dcf = {"wacc": pct(dd["wacc"]["wacc"]), "cost_of_equity": pct(dd["wacc"]["cost_of_equity"]),
               "levered_beta": f"{dd['wacc']['levered_beta']:.2f}", "terminal_share": pct(dd["terminal_share"]),
               "implied_exit_multiple": f"{dd['implied_exit_multiple']:.1f}x",
               "projection": [{k: (money(v) if k != "year" else v) for k, v in row.items()} for row in dd["projection"]]}

    # ── second-line review content ──
    e = res.get("earnings") or {}
    earnings = None
    if e:
        earnings = {"reported": money(e["reported"]), "management_adjusted": money(e["management_adjusted"]),
                    "normalized": money(e["normalized"]), "accepted": money(e["accepted"]), "claimed": money(e["claimed"]),
                    "rows": [{"description": r["description"], "category": r["category"].replace("_", " "), "support": r["support"],
                              "amount": money(r["amount"]), "accepted_pct": pct(r["accepted_pct"]), "accepted": money(r["accepted"])}
                             for r in e["rows"]]}
    comparison = [{"assumption": r["assumption"], "first_line": fmt(r["first_line"], r["unit"]),
                   "second_line": fmt(r["second_line"], r["unit"]),
                   "delta": (f"{r['delta'] * 100:+.2f}pt" if r["delta_kind"] == "pt" else pct(r["delta"], signed=True))
                   if r["delta"] is not None else "—", "status": r["status"]}
                  for r in res.get("first_line_comparison") or []]
    d = res.get("downside")
    downside = None
    if d:
        sh = d["shocks"]
        downside = {"mid": money(d["mid"]), "low": money(d["low"]), "high": money(d["high"]), "ltv": pct(d.get("ltv_mid")),
                    "coverage": f"{d['coverage_mid']:.2f}x" if d.get("coverage_mid") else "—",
                    "shocks": f"EBITDA {sh['stress_ebitda'] * 100:+.0f}%, multiples {sh['stress_multiple']:+.1f}x, "
                              f"discount rate {sh['stress_wacc'] * 100:+.1f}pt"}
    rv = res.get("reserve")
    reserve = None
    if rv:
        reserve = {"pv_mid": money(rv["pv_mid"]), "reserve_mid": money(rv["reserve_mid"]), "reserve_pct": pct(rv["reserve_pct_mid"]),
                   "reserve_min": money(min(rv["reserve_range"])), "reserve_max": money(max(rv["reserve_range"])),
                   "years": f"{rv['years']:g}", "rate": pct(rv["rate"])}
    tests = [{"label": t["label"], "value": fmt(t["value"], t["unit"]), "limit": ("≤ " if t["kind"] == "max" else "≥ ") + fmt(t["limit"], t["unit"]),
              "result": "Pass" if t["pass"] else "Fail"} for t in res.get("policy_tests") or []]
    op = case.get("opinion")
    opinion = None
    if op:
        opinion = {**op, "by_name": user(op["by"])["name"], "current": op["run_id"] == run["id"]}
    rag_label = {"green": "Green", "amber": "Amber", "red": "Red", "grey": "n/a"}[c.get("rag", "grey")]
    concl["rag"] = rag_label

    summary_line = (f"{measure} {concl['mid']} (range {concl['low']} to {concl['high']}; USD millions), "
                    f"{concl['vs_first_line']} versus the first-line view.")
    trail = store.audit_trail(case_id)
    chain = store.verify_chain()
    f = {
        "institution": settings()["app"]["institution"], "units": "USD millions",
        "generated_at": store.now()[:16].replace("T", " ") + " UTC", "generated_by": user(actor)["name"],
        "status": case["status"], "locked": bool(case["locked"]),
        "deal": deal,
        "workflow": {"id": t["id"], "name": t["name"], "tagline": t["tagline"], "description": t["description"].strip(),
                     "methods": [r["label"] for r in results]},
        "results": results, "conclusion": concl, "key_inputs": key_inputs, "adjustments": adjustments,
        "recommendations": recs, "approvals": approvals, "waterfall": waterfall, "dcf": dcf,
        "checks": run["checks"], "summary_line": summary_line,
        "opinion": opinion, "earnings": earnings, "comparison": comparison, "downside": downside, "reserve": reserve,
        "policy_tests": tests,
        "run": {"id": run["id"], "ts": run["ts"][:16].replace("T", " "), "inputs_hash": run["inputs_hash"],
                "engine": run["engine_versions"]},
        "audit": {"entries": len(trail), "chain_ok": chain["ok"], "chain_head": chain.get("head", "")},
    }
    f["findings_hash"] = hashlib.sha256(json.dumps({k: f[k] for k in ("deal", "results", "conclusion", "key_inputs",
                                                                       "adjustments")}, sort_keys=True).encode()).hexdigest()[:16]
    return f
