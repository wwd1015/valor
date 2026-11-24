"""Application services. The UI calls only these; each state change writes the audit log."""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime

import pandas as pd

from valor import store
from valor.config import settings, user
from valor.data import get_source
from valor.data.resolvers import PullContext, resolve
from valor.engine import checks as checks_mod
from valor.engine import run_valuation as engine_run
from valor.workflow import template

EDITABLE = {"draft", "returned"}


class ReviewError(Exception):
    """A request the workflow does not allow (shown to the user as-is)."""


# ── cases ────────────────────────────────────────────────────────────

def list_cases() -> list[dict]:
    return store.rows("SELECT * FROM cases ORDER BY created_at DESC")


def get_case(case_id: str) -> dict:
    c = store.one("SELECT * FROM cases WHERE id = ?", (case_id,))
    if not c:
        raise ReviewError(f"case {case_id} not found")
    c["deal"] = json.loads(c["deal"]) if c.get("deal") else {}
    c["claims"] = json.loads(c["claims"]) if c.get("claims") else []
    c["extras"] = json.loads(c["extras"]) if c.get("extras") else {}
    c["opinion"] = json.loads(c["opinion"]) if c.get("opinion") else None
    return c


def _new_case_id() -> str:
    year = datetime.now().year
    n = store.one("SELECT COUNT(*) AS n FROM cases")["n"] + 1
    return f"VAL-{year}-{n:04d}"


def create_case(deal_id: str, workflow: str, actor: str) -> str:
    deal = get_source().deal(deal_id)
    t = template(workflow)
    cid = _new_case_id()
    ts = store.now()
    store.execute(
        "INSERT INTO cases (id, deal_id, borrower_id, borrower_name, sector, workflow, status, created_by, created_at, "
        "updated_at, deal) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (cid, deal_id, deal["borrower_id"], deal["borrower_name"], deal["sector"], workflow, "draft", actor, ts, ts,
         json.dumps(deal, default=str)))
    store.audit(cid, actor, "case_created", details={"deal_id": deal_id, "workflow": t["name"],
                                                    "borrower": deal["borrower_name"]})
    return cid


def _touch(case_id: str) -> None:
    store.execute("UPDATE cases SET updated_at = ? WHERE id = ?", (store.now(), case_id))


def ensure_editable(case: dict) -> None:
    if case["locked"]:
        raise ReviewError("This case is approved and locked. No further changes are allowed.")
    if case["status"] not in EDITABLE:
        raise ReviewError(f"The case is {case['status']}; it can only be changed after it is sent back.")


# ── data pull ────────────────────────────────────────────────────────

def pull_data(case_id: str, actor: str) -> dict:
    case = get_case(case_id)
    ensure_editable(case)
    src = get_source()
    ctx = PullContext(src, case["deal_id"])
    t = template(case["workflow"])
    existing = {r["key"]: r for r in store.rows("SELECT * FROM case_inputs WHERE case_id = ?", (case_id,))}
    specs, ord_ = [], 0
    claims = []
    addbacks = []
    acceptance = settings()["policy"]["addback_acceptance"]
    for g in t["input_groups"]:
        if g.get("dynamic") == "ebitda_adjustments":
            for row in ctx.addbacks.itertuples():
                addbacks.append({"adj_id": row.adj_id, "description": row.description, "category": row.category,
                                 "amount": float(row.amount_musd), "support": row.support})
                specs.append({"key": f"addback.{row.adj_id}", "label": f"{row.description} ({row.amount_musd:.1f})",
                              "unit": "pct", "group": g["id"], "used_by": ["earnings"],
                              "resolved": (float(acceptance.get(row.category, 0.0)),
                                           f"Policy default for {row.category.replace('_', ' ')} · {row.support}")})
            continue
        if g.get("dynamic") == "capital_structure":
            for row in ctx.capital.itertuples():
                claims.append({"claim_id": row.claim_id, "claim_class": row.claim_class, "priority": int(row.priority),
                               "bank_share": float(row.bank_share), "secured": bool(row.secured)})
                specs.append({"key": f"claim.{row.claim_id}", "label": f"P{int(row.priority)} · {row.claim_class}",
                              "unit": "musd", "group": g["id"], "used_by": ["waterfall"],
                              "resolved": (float(row.amount_musd), f"CAPITAL_STRUCTURE.amount_musd ({row.claim_id})")})
            continue
        for i in g.get("inputs", []):
            r = resolve(i["source"], ctx)
            specs.append({**i, "group": g["id"], "resolved": (r.value, r.ref)})

    changed = 0
    with store.conn() as c:
        for s in specs:
            ord_ += 1
            val, ref = s["resolved"]
            prev = existing.get(s["key"])
            if prev and prev["value"] != prev["source_value"]:
                value = prev["value"]           # keep the analyst's adjustment; only the source moves
            else:
                value = val
            if prev and prev["source_value"] != val:
                changed += 1
            c.execute("INSERT OR REPLACE INTO case_inputs (case_id, key, label, unit, grp, ord, value, source_value, "
                      "source_ref, used_by, meta) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (case_id, s["key"], s["label"], s["unit"], s["group"], ord_, value, val, ref,
                       ",".join(s.get("used_by", [])), json.dumps({"note": s.get("note")})))
        for name, df in ctx.tables().items():
            c.execute("INSERT OR REPLACE INTO pulled_tables (case_id, name, data) VALUES (?,?,?)",
                      (case_id, name, df.to_json(orient="records")))
        extras = {"addbacks": addbacks, "first_line": {k: v for k, v in ctx.first_line.items()}}
        c.execute("UPDATE cases SET data_pulled_at = ?, data_source = ?, claims = ?, extras = ?, updated_at = ? WHERE id = ?",
                  (store.now(), src.label, json.dumps(claims), json.dumps(extras, default=str), store.now(), case_id))
    store.audit(case_id, actor, "data_pulled", details={
        "source": src.label, "inputs": len(specs), "repull": bool(existing), "source_values_changed": changed,
        "tables": list(ctx.tables().keys())})
    return {"inputs": len(specs), "changed": changed}


def pulled_tables(case_id: str) -> dict[str, pd.DataFrame]:
    out = {}
    for r in store.rows("SELECT name, data FROM pulled_tables WHERE case_id = ?", (case_id,)):
        out[r["name"]] = pd.DataFrame(json.loads(r["data"]))
    return out


# ── inputs ───────────────────────────────────────────────────────────

def get_inputs(case_id: str) -> list[dict]:
    return store.rows("SELECT * FROM case_inputs WHERE case_id = ? ORDER BY ord", (case_id,))


def input_values(case_id: str) -> dict[str, float]:
    return {r["key"]: r["value"] for r in get_inputs(case_id)}


def inputs_hash(values: dict) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:16]


def adjust_input(case_id: str, key: str, new_value: float, rationale: str, actor: str,
                 event: str = "input_adjusted", details: dict | None = None) -> None:
    case = get_case(case_id)
    ensure_editable(case)
    rationale = (rationale or "").strip()
    if len(rationale) < settings()["review"]["min_rationale_chars"]:
        raise ReviewError("A rationale is required for every input change (at least a short sentence).")
    row = store.one("SELECT * FROM case_inputs WHERE case_id = ? AND key = ?", (case_id, key))
    if not row:
        raise ReviewError(f"unknown input {key}")
    new_value = float(new_value)
    if row["value"] == new_value:
        raise ReviewError("The new value is the same as the current value.")
    store.execute("UPDATE case_inputs SET value = ? WHERE case_id = ? AND key = ?", (new_value, case_id, key))
    store.audit(case_id, actor, event, field=key, label=row["label"], old=row["value"], new=new_value,
                source=row["source_value"], rationale=rationale,
                details={"unit": row["unit"], "source_ref": row["source_ref"], **(details or {})})
    _touch(case_id)


def adjustments(case_id: str) -> list[dict]:
    """Net adjustments: every input whose value differs from source, with its latest rationale."""
    trail = [e for e in store.audit_trail(case_id) if e["event"] in ("input_adjusted", "recommendation_applied")]
    last = {}
    for e in trail:
        last[e["field"]] = e
    out = []
    for r in get_inputs(case_id):
        if r["value"] != r["source_value"]:
            e = last.get(r["key"], {})
            out.append({"key": r["key"], "label": r["label"], "unit": r["unit"], "source_value": r["source_value"],
                        "value": r["value"], "source_ref": r["source_ref"], "rationale": e.get("rationale"),
                        "actor": e.get("actor"), "ts": e.get("ts"), "via_agent": e.get("event") == "recommendation_applied"})
    return out


# ── valuation ────────────────────────────────────────────────────────

def run_valuation(case_id: str, actor: str) -> dict:
    case = get_case(case_id)
    if case["locked"]:
        raise ReviewError("This case is approved and locked.")
    ensure_editable(case)
    if not case["data_pulled_at"]:
        raise ReviewError("Pull the data before running the valuation.")
    t = template(case["workflow"])
    values = input_values(case_id)
    res = engine_run(t, values, case["claims"], settings()["review"]["first_line_variance_flag"],
                     extras=case["extras"], policy=settings()["policy"])
    hist = checks_mod.history_from_tables(pulled_tables(case_id))
    chk = checks_mod.run(t, values, res, hist, settings()["policy"])
    versions = {m["method"]: m["version"] for m in res["methods"]}
    h = inputs_hash(values)
    rid = store.execute("INSERT INTO valuation_runs (case_id, ts, actor, inputs_hash, results, checks, engine_versions) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (case_id, store.now(), actor, h, json.dumps(res), json.dumps(chk), json.dumps(versions)))
    c = res["conclusion"]
    store.audit(case_id, actor, "valuation_run", details={
        "run_id": rid, "inputs_hash": h, "measure": c["measure"], "low": c["low"], "mid": c["mid"], "high": c["high"],
        "vs_first_line": c["vs_first_line"], "rag": c.get("rag"), "checks": len(chk), "engine": versions})
    _touch(case_id)
    explain_async(case_id)
    return latest_run(case_id)


def latest_run(case_id: str) -> dict | None:
    r = store.one("SELECT * FROM valuation_runs WHERE case_id = ? ORDER BY id DESC LIMIT 1", (case_id,))
    if r:
        for k in ("results", "checks", "engine_versions"):
            r[k] = json.loads(r[k]) if r[k] else None
    return r


def run_is_current(case_id: str) -> bool:
    r = latest_run(case_id)
    return bool(r) and r["inputs_hash"] == inputs_hash(input_values(case_id))


_explaining: set[int] = set()


def explanation_pending(run_id: int) -> bool:
    return run_id in _explaining


def explain_async(case_id: str, actor: str = "agent:auto") -> None:
    """Write the agent commentary for the latest run in the background (Claude takes 15-20 s)."""
    if not settings()["agent"].get("auto_explain", True):
        return
    run = latest_run(case_id)
    if not run or run.get("explanation") or run["id"] in _explaining:
        return
    _explaining.add(run["id"])

    def work():
        try:
            explain(case_id, actor, run_id=run["id"])
        except Exception:  # noqa: BLE001 - commentary is optional; failure leaves the regenerate link
            pass
        finally:
            _explaining.discard(run["id"])
    threading.Thread(target=work, daemon=False).start()


def explain(case_id: str, actor: str, run_id: int | None = None) -> str:
    from valor.agent import tasks
    case = get_case(case_id)
    run = latest_run(case_id)
    if run_id is not None:
        r = store.one("SELECT * FROM valuation_runs WHERE id = ?", (run_id,))
        if r:
            for k in ("results", "checks", "engine_versions"):
                r[k] = json.loads(r[k]) if r[k] else None
            run = r
    if not run:
        raise ReviewError("Run the valuation first.")
    text, meta = tasks.explain_results(case, run, get_inputs(case_id))
    store.execute("UPDATE valuation_runs SET explanation = ?, explanation_source = ? WHERE id = ?",
                  (text, meta["mode"], run["id"]))
    store.audit(case_id, actor, "agent_explained", details={"run_id": run["id"], **meta})
    return text


# ── recommendations ──────────────────────────────────────────────────

def recommendations(case_id: str) -> list[dict]:
    return store.rows("SELECT * FROM recommendations WHERE case_id = ? ORDER BY id DESC", (case_id,))


def generate_recommendations(case_id: str, actor: str) -> int:
    from valor.agent import tasks
    case = get_case(case_id)
    ensure_editable(case)
    run = latest_run(case_id)
    if not run:
        raise ReviewError("Run the valuation first: recommendations are made against a valuation run.")
    inputs = get_inputs(case_id)
    recs, meta = tasks.recommend(case, run, inputs)
    known = {i["key"]: i for i in inputs}
    n = 0
    for r in recs:
        field = r.get("field") if r.get("field") in known else None
        proposed = r.get("proposed_value") if field else None
        rid = store.execute(
            "INSERT INTO recommendations (case_id, run_id, ts, source, kind, field, title, rationale, severity, "
            "current_value, proposed_value) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (case_id, run["id"], store.now(), meta["mode"], "adjustment" if proposed is not None else "flag",
             field, r["title"], r["rationale"], r.get("severity", "medium"),
             known[field]["value"] if field else None, proposed))
        store.audit(case_id, f"agent:{meta['mode']}", "recommendation_made", field=field,
                    label=known[field]["label"] if field else None,
                    old=known[field]["value"] if field else None, new=proposed, rationale=r["rationale"],
                    details={"recommendation_id": rid, "title": r["title"], "severity": r.get("severity"),
                             "run_id": run["id"], "agent_run": meta.get("run_id")})
        n += 1
    store.audit(case_id, actor, "agent_recommendations_requested", details={"count": n, **meta})
    return n


def decide_recommendation(rec_id: int, decision: str, actor: str, value: float | None = None, note: str = "") -> None:
    rec = store.one("SELECT * FROM recommendations WHERE id = ?", (rec_id,))
    if not rec or rec["status"] != "open":
        raise ReviewError("This recommendation has already been decided.")
    case = get_case(rec["case_id"])
    ensure_editable(case)
    note = (note or "").strip()
    final = None
    if decision == "reject":
        if len(note) < settings()["review"]["min_rationale_chars"]:
            raise ReviewError("Say why you are rejecting the recommendation.")
    elif decision in ("accept", "edit") and rec["field"]:
        final = rec["proposed_value"] if decision == "accept" else value
        if final is None:
            raise ReviewError("Enter the value to apply.")
        if decision == "edit" and len(note) < settings()["review"]["min_rationale_chars"]:
            raise ReviewError("Say why you changed the agent's proposed value.")
        rationale = f"Agent recommendation #{rec_id} {'accepted' if decision == 'accept' else 'edited'}: {rec['title']}."
        if note:
            rationale += f" {note}"
        cur = store.one("SELECT value FROM case_inputs WHERE case_id = ? AND key = ?", (rec["case_id"], rec["field"]))
        if cur and cur["value"] != float(final):
            adjust_input(rec["case_id"], rec["field"], float(final), rationale, actor, event="recommendation_applied",
                         details={"recommendation_id": rec_id, "agent_proposed": rec["proposed_value"]})
    status = {"accept": "accepted", "edit": "edited", "reject": "rejected"}[decision]
    store.execute("UPDATE recommendations SET status = ?, decided_by = ?, decided_at = ?, final_value = ?, "
                  "decision_note = ? WHERE id = ?", (status, actor, store.now(), final, note, rec_id))
    store.audit(rec["case_id"], actor, f"recommendation_{status}", field=rec["field"], old=rec["current_value"],
                new=final, rationale=note or None,
                details={"recommendation_id": rec_id, "title": rec["title"], "agent_proposed": rec["proposed_value"]})


# ── opinion ──────────────────────────────────────────────────────────

def suggested_verdict(case_id: str) -> str | None:
    from valor.engine.review import suggested_verdict as sv
    run = latest_run(case_id)
    if not run:
        return None
    r = run["results"]
    highs = sum(1 for c in run["checks"] or [] if c["severity"] == "high")
    return sv(r["conclusion"].get("rag", "grey"), r.get("policy_tests") or [], highs)


def set_opinion(case_id: str, actor: str, verdict: str, rationale: str, conditions: list[str] | None = None,
                risks: list[dict] | None = None, questions: list[str] | None = None, source: str = "analyst") -> dict:
    from valor.engine.review import VERDICTS
    case = get_case(case_id)
    ensure_editable(case)
    run = latest_run(case_id)
    if not run:
        raise ReviewError("Run the valuation before forming an opinion.")
    if verdict not in VERDICTS:
        raise ReviewError("Choose a verdict.")
    if len((rationale or "").strip()) < settings()["review"]["min_rationale_chars"]:
        raise ReviewError("Give the reason for your opinion.")
    if verdict != "concur" and not [c for c in (conditions or []) if c.strip()] and verdict == "concur_with_exceptions":
        raise ReviewError("List the exceptions or conditions behind 'Concur with exceptions'.")
    prev = case["opinion"]
    op = {"verdict": verdict, "verdict_label": VERDICTS[verdict], "rationale": rationale.strip(),
          "conditions": [c.strip() for c in (conditions or []) if c.strip()],
          "risks": risks if risks is not None else (prev or {}).get("risks", []),
          "questions": questions if questions is not None else (prev or {}).get("questions", []),
          "suggested": suggested_verdict(case_id), "run_id": run["id"], "by": actor, "ts": store.now(), "source": source}
    store.execute("UPDATE cases SET opinion = ?, updated_at = ? WHERE id = ?", (json.dumps(op), store.now(), case_id))
    store.audit(case_id, actor, "opinion_set", old=(prev or {}).get("verdict_label"), new=op["verdict_label"],
                rationale=op["rationale"], details={"run_id": run["id"], "conditions": op["conditions"],
                                                    "suggested": op["suggested"]})
    return op


def draft_opinion(case_id: str, actor: str) -> dict:
    """Agent drafts risks, mitigants and questions for the first line; the analyst decides the verdict."""
    from valor.agent import tasks
    case = get_case(case_id)
    ensure_editable(case)
    run = latest_run(case_id)
    if not run:
        raise ReviewError("Run the valuation first.")
    data, meta = tasks.draft_opinion(case, run, get_inputs(case_id), suggested_verdict(case_id))
    draft = {**data, "source": meta["mode"], "run_id": run["id"], "unverified": meta.get("unverified_numbers", [])}
    extras = {**case["extras"], "opinion_draft": draft}
    store.execute("UPDATE cases SET extras = ? WHERE id = ?", (json.dumps(extras, default=str), case_id))
    store.audit(case_id, actor, "agent_opinion_drafted", details={"run_id": run["id"], "verdict": data["verdict"], **meta})
    return draft


# ── what-if and reviewer challenges ──────────────────────────────────

def _summary(t: dict, res: dict, checks_high: int = 0) -> dict:
    from valor.engine.review import suggested_verdict as sv
    c = res["conclusion"]
    out = {"measure": c["measure"], "low": c["low"], "mid": c["mid"], "high": c["high"], "vs_first_line": c.get("vs_first_line"),
           "rag": c.get("rag"), "normalized_ebitda": (res.get("earnings") or {}).get("normalized")}
    if c["measure"] == "enterprise_value":
        out.update(ltv=c.get("ltv_mid"), coverage=c.get("coverage_mid"),
                   downside=(res.get("downside") or {}).get("mid"), downside_ltv=(res.get("downside") or {}).get("ltv_mid"))
    else:
        rv = res.get("reserve") or {}
        out.update(recovery_pct=c.get("recovery_pct_mid"), reserve=rv.get("reserve_mid"))
    out["policy_fail"] = [x["label"] for x in res.get("policy_tests") or [] if not x["pass"]]
    out["suggested_verdict"] = sv(c.get("rag", "grey"), res.get("policy_tests") or [], checks_high)
    return out


def what_if(case_id: str, overrides: dict[str, float]) -> dict:
    """Re-run the engine with some inputs overridden. Nothing is saved: the case of record is untouched."""
    case = get_case(case_id)
    if not case["data_pulled_at"]:
        raise ReviewError("No data pulled yet.")
    t = template(case["workflow"])
    values = input_values(case_id)
    unknown = [k for k in overrides if k not in values]
    if unknown:
        raise ReviewError(f"Unknown input(s): {', '.join(unknown)}")
    cfg = settings()
    base = engine_run(t, values, case["claims"], cfg["review"]["first_line_variance_flag"], extras=case["extras"], policy=cfg["policy"])
    alt = engine_run(t, {**values, **overrides}, case["claims"], cfg["review"]["first_line_variance_flag"],
                     extras=case["extras"], policy=cfg["policy"])
    return {"base": _summary(t, base), "what_if": _summary(t, alt), "overrides": overrides}


def challenges(case_id: str) -> list[dict]:
    rows = store.rows("SELECT * FROM challenges WHERE case_id = ? ORDER BY id", (case_id,))
    for r in rows:
        r["impact"] = json.loads(r["impact"]) if r["impact"] else {}
    return rows


def send_back_with_challenges(case_id: str, actor: str, overrides: dict[str, float], comment: str) -> int:
    """The checker challenges specific assumptions: each becomes an item the maker must accept or answer."""
    case = get_case(case_id)
    _check_reviewer(case, actor)
    if not overrides:
        raise ReviewError("Add at least one assumption to challenge.")
    if len((comment or "").strip()) < settings()["review"]["min_rationale_chars"]:
        raise ReviewError("Explain the challenge for the analyst.")
    rows = {r["key"]: r for r in get_inputs(case_id)}
    run = latest_run(case_id)
    combined = what_if(case_id, overrides)
    for key, val in overrides.items():
        single = what_if(case_id, {key: val})
        cid = store.execute(
            "INSERT INTO challenges (case_id, ts, raised_by, run_id, field, label, unit, analyst_value, proposed_value, comment, impact) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (case_id, store.now(), actor, run["id"] if run else None, key, rows[key]["label"], rows[key]["unit"], rows[key]["value"],
             float(val), comment.strip(), json.dumps({"base": single["base"], "what_if": single["what_if"]})))
        store.audit(case_id, actor, "challenge_raised", field=key, label=rows[key]["label"], old=rows[key]["value"], new=val,
                    source=rows[key]["source_value"], rationale=comment.strip(),
                    details={"challenge_id": cid, "unit": rows[key]["unit"], "mid_before": single["base"]["mid"],
                             "mid_after": single["what_if"]["mid"]})
    b, w = combined["base"], combined["what_if"]
    summary = (f"{len(overrides)} assumption challenge(s). Combined effect: {b['mid']:,.1f} → {w['mid']:,.1f}. {comment.strip()}")
    send_back(case_id, actor, summary)
    return len(overrides)


def resolve_challenge(challenge_id: int, decision: str, actor: str, response: str = "") -> None:
    ch = store.one("SELECT * FROM challenges WHERE id = ?", (challenge_id,))
    if not ch or ch["status"] != "open":
        raise ReviewError("This challenge has already been resolved.")
    case = get_case(ch["case_id"])
    ensure_editable(case)
    response = (response or "").strip()
    if decision == "decline" and len(response) < settings()["review"]["min_rationale_chars"]:
        raise ReviewError("Explain why you are keeping your value; the reviewer will read it.")
    if decision == "accept":
        cur = store.one("SELECT value FROM case_inputs WHERE case_id = ? AND key = ?", (ch["case_id"], ch["field"]))
        if cur and cur["value"] != ch["proposed_value"]:
            adjust_input(ch["case_id"], ch["field"], ch["proposed_value"],
                         f"Reviewer challenge #{challenge_id} accepted: {ch['comment']}" + (f" {response}" if response else ""),
                         actor, event="challenge_applied", details={"challenge_id": challenge_id, "raised_by": ch["raised_by"]})
    status = "accepted" if decision == "accept" else "declined"
    store.execute("UPDATE challenges SET status = ?, response = ?, resolved_by = ?, resolved_at = ? WHERE id = ?",
                  (status, response, actor, store.now(), challenge_id))
    store.audit(ch["case_id"], actor, f"challenge_{status}", field=ch["field"], label=ch["label"], old=ch["analyst_value"],
                new=ch["proposed_value"], rationale=response or None, details={"challenge_id": challenge_id, "unit": ch["unit"]})


# ── maker-checker ────────────────────────────────────────────────────

def reviews(case_id: str) -> list[dict]:
    return store.rows("SELECT * FROM reviews WHERE case_id = ? ORDER BY id", (case_id,))


def submit(case_id: str, actor: str, comment: str) -> None:
    case = get_case(case_id)
    ensure_editable(case)
    if not latest_run(case_id):
        raise ReviewError("Run the valuation before submitting.")
    if not run_is_current(case_id):
        raise ReviewError("Inputs changed since the last valuation run. Re-run the valuation before submitting.")
    open_recs = [r for r in recommendations(case_id) if r["status"] == "open"]
    if open_recs:
        raise ReviewError(f"Decide the {len(open_recs)} open agent recommendation(s) before submitting.")
    open_ch = [c for c in challenges(case_id) if c["status"] == "open"]
    if open_ch:
        raise ReviewError(f"Answer the {len(open_ch)} open reviewer challenge(s) before resubmitting.")
    op = case["opinion"]
    if not op:
        raise ReviewError("Record your opinion (Concur / Concur with exceptions / Do not concur) before submitting.")
    if op["run_id"] != latest_run(case_id)["id"]:
        raise ReviewError("The valuation was re-run after your opinion. Confirm the opinion against the latest run.")
    store.execute("UPDATE cases SET status = 'submitted', submitted_by = ?, updated_at = ? WHERE id = ?",
                  (actor, store.now(), case_id))
    store.execute("INSERT INTO reviews (case_id, ts, actor, action, comment) VALUES (?,?,?,?,?)",
                  (case_id, store.now(), actor, "submit", comment))
    run = latest_run(case_id)
    store.audit(case_id, actor, "submitted", rationale=comment or None,
                details={"run_id": run["id"], "inputs_hash": run["inputs_hash"]})


def _check_reviewer(case: dict, actor: str) -> None:
    if user(actor)["role"] not in ("reviewer", "admin"):
        raise ReviewError("Only a reviewer can approve or send back a case.")
    if case["status"] != "submitted":
        raise ReviewError("The case has not been submitted for review.")
    if actor == case["submitted_by"] and not settings()["review"]["allow_self_approval"]:
        raise ReviewError("Maker-checker: you submitted this case, so someone else must review it.")


def send_back(case_id: str, actor: str, comment: str) -> None:
    case = get_case(case_id)
    _check_reviewer(case, actor)
    if len((comment or "").strip()) < settings()["review"]["min_rationale_chars"]:
        raise ReviewError("Add a comment telling the analyst what to change.")
    store.execute("UPDATE cases SET status = 'returned', updated_at = ? WHERE id = ?", (store.now(), case_id))
    store.execute("INSERT INTO reviews (case_id, ts, actor, action, comment) VALUES (?,?,?,?,?)",
                  (case_id, store.now(), actor, "send_back", comment))
    store.audit(case_id, actor, "sent_back", rationale=comment)


def approve(case_id: str, actor: str, comment: str) -> None:
    case = get_case(case_id)
    _check_reviewer(case, actor)
    run = latest_run(case_id)
    store.execute("UPDATE cases SET status = 'approved', approved_by = ?, locked = 1, updated_at = ? WHERE id = ?",
                  (actor, store.now(), case_id))
    store.execute("INSERT INTO reviews (case_id, ts, actor, action, comment) VALUES (?,?,?,?,?)",
                  (case_id, store.now(), actor, "approve", comment))
    store.audit(case_id, actor, "approved", rationale=comment or None,
                details={"run_id": run["id"] if run else None, "inputs_hash": run["inputs_hash"] if run else None})
    store.audit(case_id, actor, "locked", details={"reason": "approved"})
