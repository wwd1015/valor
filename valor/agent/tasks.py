"""The agent's tasks. Each builds a payload from engine output, asks Claude for judgment or
language, and has a deterministic mock used offline or when the CLI is unavailable.

Claude never produces a valuation figure. It may *propose input values* (which a person must
accept, and which the engine then uses), and it writes prose that is checked by numguard."""

from __future__ import annotations

import json

from valor.agent import numguard
from valor.agent.runner import call, prompt_text
from valor.workflow import template

SEVERITY = ["high", "medium", "low"]


def _pct(x):
    return f"{x:.1%}" if x is not None else "n/a"


def compact_results(run: dict) -> dict:
    res = run["results"]
    methods = []
    for m in res["methods"]:
        d = m["details"]
        keep = {"method": m["label"], "measure": m["measure"], "low": m["low"], "mid": m["mid"], "high": m["high"],
                "weight": d.get("weight")}
        if m["method"] == "dcf":
            keep.update(wacc=d["wacc"]["wacc"], terminal_value_share=d["terminal_share"],
                        implied_exit_multiple=d["implied_exit_multiple"], pv_fcf=d["pv_fcf"], pv_terminal=d["pv_terminal"])
        if m["method"] in ("liquidation", "distressed_gc"):
            keep["value_before_waterfall"] = d.get("value_basis")
            keep["bank_recovery_pct"] = {s: d["waterfall"][s]["bank_recovery_pct"] for s in ("low", "high")}
        methods.append(keep)
    out = {"methods": methods, "conclusion": res["conclusion"]}
    e = res.get("earnings")
    if e:
        out["earnings"] = {k: e[k] for k in ("reported", "management_adjusted", "normalized", "claimed", "accepted")}
        out["earnings"]["add_backs"] = [{k: r[k] for k in ("description", "category", "support", "amount", "accepted_pct")}
                                        for r in e["rows"]]
    if res.get("downside"):
        d = res["downside"]
        out["downside"] = {k: d.get(k) for k in ("low", "mid", "high", "ltv_mid", "coverage_mid", "shocks")}
    if res.get("reserve"):
        out["reserve"] = res["reserve"]
    if res.get("policy_tests"):
        out["policy_tests"] = res["policy_tests"]
    if res.get("first_line_comparison"):
        out["first_line_comparison"] = res["first_line_comparison"]
    return out


def case_summary(case: dict) -> dict:
    d = case["deal"]
    return {"case_id": case["id"], "borrower": case["borrower_name"], "sector": case["sector"],
            "workflow": template(case["workflow"])["name"], "facility": d.get("facility_name"),
            "lien": d.get("lien_position"), "risk_status": d.get("risk_status"),
            "commitment_musd": d.get("commitment_musd"), "outstanding_musd": d.get("outstanding_musd"),
            "first_line_method": d.get("first_line_method"), "units": "USD millions"}


def input_table(inputs: list[dict]) -> list[dict]:
    return [{"key": i["key"], "label": i["label"], "unit": i["unit"], "value": i["value"],
             "source_value": i["source_value"], "source": i["source_ref"]} for i in inputs]


# ── recommendations ──────────────────────────────────────────────────

REC_SCHEMA = {
    "type": "object",
    "properties": {"recommendations": {"type": "array", "maxItems": 6, "items": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "rationale": {"type": "string"},
            "severity": {"type": "string", "enum": SEVERITY},
            "field": {"type": ["string", "null"], "description": "input key to adjust, or null for a flag"},
            "proposed_value": {"type": ["number", "null"], "description": "new input value, in the input's own unit"},
        },
        "required": ["title", "rationale", "severity", "field", "proposed_value"]}}},
    "required": ["recommendations"],
}


def recommend(case: dict, run: dict, inputs: list[dict]) -> tuple[list[dict], dict]:
    payload = {"case": case_summary(case), "inputs": input_table(inputs), "results": compact_results(run),
               "checks": run["checks"]}
    prompt = prompt_text("recommend", payload=json.dumps(payload, indent=1, default=str))

    def mock():
        out = []
        for c in run["checks"]:
            out.append({"title": c["title"], "rationale": c["detail"], "severity": c["severity"],
                        "field": c.get("field") if c.get("suggested") is not None else None,
                        "proposed_value": c.get("suggested")})
        if not out:
            out.append({"title": "No material issues found", "severity": "low", "field": None, "proposed_value": None,
                        "rationale": "The deterministic checks raised nothing. Confirm the projections against the "
                                     "borrower's latest management reporting before submitting."})
        return {"recommendations": out}

    data, meta = call("recommend", case["id"], prompt, REC_SCHEMA, mock)
    return data.get("recommendations", []), meta


# ── explanation ──────────────────────────────────────────────────────

EXPLAIN_SCHEMA = {"type": "object", "properties": {"explanation": {"type": "string"}}, "required": ["explanation"]}


def explain_results(case: dict, run: dict, inputs: list[dict]) -> tuple[str, dict]:
    payload = {"case": case_summary(case), "results": compact_results(run), "checks": run["checks"]}
    prompt = prompt_text("explain", payload=json.dumps(payload, indent=1, default=str))

    def mock():
        return {"explanation": _mock_summary(case, run)}

    data, meta = call("explain", case["id"], prompt, EXPLAIN_SCHEMA, mock)
    text = data.get("explanation", "")
    meta["unverified_numbers"] = numguard.unverified_numbers(text, payload)
    return text, meta


def _mock_summary(case: dict, run: dict) -> str:
    c = run["results"]["conclusion"]
    ms = run["results"]["methods"]
    lead = max(ms, key=lambda m: m["details"].get("weight") or 0)
    if c["measure"] == "enterprise_value":
        s = (f"The reconciled enterprise value for {case['borrower_name']} is {c['mid']:,.1f} "
             f"(range {c['low']:,.1f} to {c['high']:,.1f}), weighted most heavily to the {lead['label'].lower()}. ")
        if c.get("coverage_mid") is not None:
            s += f"At the midpoint, value after senior debt covers the bank's commitment {c['coverage_mid']:.2f} times. "
    else:
        s = (f"The bank's estimated recovery is {c['mid']:,.1f} (range {c['low']:,.1f} to {c['high']:,.1f}), "
             f"or {_pct(c.get('recovery_pct_mid'))} of exposure. ")
    if c.get("vs_first_line") is not None:
        s += f"This is {abs(c['vs_first_line']):.1%} {'above' if c['vs_first_line'] > 0 else 'below'} the first-line view."
    n = len(run["checks"])
    if n:
        s += f" The review checks raised {n} point(s) for attention."
    return s


# ── report narrative ─────────────────────────────────────────────────

NARRATIVE_SCHEMA = {"type": "object", "properties": {
    "executive_summary": {"type": "string"}, "methodology_commentary": {"type": "string"},
    "key_judgements": {"type": "string"}, "conclusion": {"type": "string"}},
    "required": ["executive_summary", "methodology_commentary", "key_judgements", "conclusion"]}


def draft_narrative(findings: dict) -> tuple[dict, dict]:
    payload = {k: findings[k] for k in ("deal", "workflow", "results", "conclusion", "adjustments", "recommendations",
                                        "opinion", "earnings", "comparison", "downside", "reserve")}
    prompt = prompt_text("narrative", payload=json.dumps(payload, indent=1, default=str))

    def mock():
        c = findings["conclusion"]
        adj = findings["adjustments"]
        return {
            "executive_summary": findings["summary_line"],
            "methodology_commentary": (f"The {findings['workflow']['name'].lower()} workflow applies "
                                       f"{', '.join(m['label'].lower() for m in findings['results'])}, reconciled by "
                                       "the weights shown. Inputs are sourced from the bank's data warehouse and market "
                                       "data feeds; every change from source is listed in the adjustments table."),
            "key_judgements": (f"{len(adj)} input(s) were adjusted from source. " if adj else
                               "No inputs were adjusted from source. ") +
                              "See the adjustments table for values and rationales.",
            "conclusion": c["statement"],
        }

    data, meta = call("narrative", findings["deal"]["case_id"], prompt, NARRATIVE_SCHEMA, mock)
    meta["unverified_numbers"] = numguard.unverified_numbers(" ".join(map(str, data.values())), payload)
    return data, meta


# ── email ────────────────────────────────────────────────────────────

EMAIL_SCHEMA = {"type": "object", "properties": {"subject": {"type": "string"}, "body": {"type": "string"}},
                "required": ["subject", "body"]}


def draft_email(findings: dict, report_link: str, subject_prefix: str, use_agent: bool = True) -> tuple[dict, dict]:
    payload = {k: findings[k] for k in ("deal", "workflow", "conclusion", "approvals", "opinion", "reserve")}
    payload["report_link"] = report_link
    prompt = prompt_text("email", payload=json.dumps(payload, indent=1, default=str), subject_prefix=subject_prefix)

    def mock():
        d = findings["deal"]
        body = (f"Hello,\n\nThe second-line valuation review for {d['borrower']} ({d['facility']}, case {d['case_id']}) "
                f"is complete.\n\n{findings['summary_line']}\n\n{findings['conclusion']['statement']}\n\n"
                f"Report: {report_link}\n\nRegards,")
        return {"subject": f"{subject_prefix} {d['borrower']}: {findings['workflow']['name'].lower()} valuation review",
                "body": body}

    data, meta = call("email", findings["deal"]["case_id"], prompt, EMAIL_SCHEMA, mock, use_agent=use_agent)
    meta["unverified_numbers"] = numguard.unverified_numbers(data.get("body", ""), payload)
    return data, meta


# ── opinion ──────────────────────────────────────────────────────────

OPINION_SCHEMA = {"type": "object", "properties": {
    "verdict": {"type": "string", "enum": ["concur", "concur_with_exceptions", "do_not_concur"]},
    "rationale": {"type": "string"},
    "conditions": {"type": "array", "maxItems": 4, "items": {"type": "string"}},
    "risks": {"type": "array", "maxItems": 3, "items": {"type": "object", "properties": {
        "risk": {"type": "string"}, "mitigant": {"type": "string"}}, "required": ["risk", "mitigant"]}},
    "questions": {"type": "array", "maxItems": 5, "items": {"type": "string"}}},
    "required": ["verdict", "rationale", "conditions", "risks", "questions"]}


def draft_opinion(case: dict, run: dict, inputs: list[dict], suggested: str | None) -> tuple[dict, dict]:
    payload = {"case": case_summary(case), "results": compact_results(run), "checks": run["checks"],
               "rule_based_suggestion": suggested}
    prompt = prompt_text("opinion", payload=json.dumps(payload, indent=1, default=str))

    def mock():
        c = run["results"]["conclusion"]
        checks = sorted(run["checks"] or [], key=lambda x: SEVERITY.index(x["severity"]))
        risks = [{"risk": x["title"], "mitigant": "Addressed through the second-line adjustments shown in the memo."
                  if x.get("field") else "Raised with the first line for support."} for x in checks[:3]]
        qs = [f"Provide support for: {x['title'].lower()}." for x in checks[:4]]
        conds = [x["title"] for x in checks if x["severity"] == "high"][:3]
        verdict = suggested or "concur"
        if verdict == "concur_with_exceptions" and not conds:
            conds = [x["title"] for x in checks[:2]] or ["Refresh the valuation at the next annual review."]
        vs = c.get("vs_first_line")
        rationale = (f"The second-line midpoint is {abs(vs):.1%} {'below' if vs < 0 else 'above'} the first-line value"
                     if vs is not None else "No first-line value to compare")
        rationale += f"; {len(checks)} review point(s) raised."
        return {"verdict": verdict, "rationale": rationale, "conditions": conds, "risks": risks, "questions": qs}

    data, meta = call("opinion", case["id"], prompt, OPINION_SCHEMA, mock)
    meta["unverified_numbers"] = numguard.unverified_numbers(json.dumps(data), payload)
    return data, meta
