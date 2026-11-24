"""End-to-end service flow: intake, data, inputs, valuation, recommendations, maker-checker, report, share."""

import sqlite3

import pytest

from valor import service, share, store
from valor.agent import numguard
from valor.report import render


def _opine(cid, verdict="concur_with_exceptions"):
    service.set_opinion(cid, "a.chen", verdict, "Supported subject to the conditions listed.", ["Refresh at next review."])


def _case(deal="D-1001", wf="performing"):
    cid = service.create_case(deal, wf, "a.chen")
    service.pull_data(cid, "a.chen")
    return cid


def test_both_workflows_run_end_to_end():
    for deal, wf, measure in (("D-1001", "performing", "enterprise_value"), ("D-2001", "troubled", "bank_recovery")):
        cid = _case(deal, wf)
        run = service.run_valuation(cid, "a.chen")
        c = run["results"]["conclusion"]
        assert c["measure"] == measure and c["low"] <= c["mid"] <= c["high"]
        service.generate_recommendations(cid, "a.chen")
        for r in service.recommendations(cid):
            service.decide_recommendation(r["id"], "reject", "a.chen", note="Considered and not adopted.")
        _opine(cid)
        service.submit(cid, "a.chen", "ready")
        service.approve(cid, "m.reyes", "ok")
        for t in render.list_templates():
            out = render.generate(cid, t["id"], "m.reyes")
            assert out["findings"]["conclusion"]["mid"]
        assert share.draft(cid, "m.reyes")["subject"]


def test_input_change_requires_rationale_and_is_audited():
    cid = _case()
    with pytest.raises(service.ReviewError):
        service.adjust_input(cid, "terminal_growth", 0.02, "", "a.chen")
    service.adjust_input(cid, "terminal_growth", 0.02, "Long-run growth for a mature logistics business.", "a.chen")
    adj = service.adjustments(cid)
    assert len(adj) == 1 and adj[0]["value"] == 0.02 and adj[0]["source_value"] == 0.025
    e = [x for x in store.audit_trail(cid) if x["event"] == "input_adjusted"][0]
    assert e["actor"] == "a.chen" and e["old_value"] == "0.025" and e["source_value"] == "0.025" and e["rationale"]


def test_repull_keeps_adjustments():
    cid = _case()
    service.adjust_input(cid, "g_y1", 0.05, "Haircut to recent history.", "a.chen")
    service.pull_data(cid, "a.chen")
    assert service.input_values(cid)["g_y1"] == 0.05


def test_maker_checker_rules():
    cid = _case()
    with pytest.raises(service.ReviewError):
        service.submit(cid, "a.chen", "")                     # no valuation run yet
    service.run_valuation(cid, "a.chen")
    service.adjust_input(cid, "erp", 0.06, "House view on equity risk premium.", "a.chen")
    with pytest.raises(service.ReviewError, match="Re-run"):
        service.submit(cid, "a.chen", "")                     # run is stale
    service.run_valuation(cid, "a.chen")
    service.generate_recommendations(cid, "a.chen")
    with pytest.raises(service.ReviewError, match="open agent"):
        service.submit(cid, "a.chen", "")
    for r in service.recommendations(cid):
        service.decide_recommendation(r["id"], "accept", "a.chen")
    service.run_valuation(cid, "a.chen")
    with pytest.raises(service.ReviewError, match="opinion"):
        service.submit(cid, "a.chen", "")
    _opine(cid)
    service.submit(cid, "a.chen", "")
    with pytest.raises(service.ReviewError):
        service.adjust_input(cid, "erp", 0.05, "Frozen while in review.", "a.chen")
    with pytest.raises(service.ReviewError, match="reviewer"):
        service.approve(cid, "j.okafor", "")                  # analyst cannot approve
    with pytest.raises(service.ReviewError):
        service.send_back(cid, "m.reyes", "")                 # comment required
    service.send_back(cid, "m.reyes", "Support the margin path with board-approved plan.")
    assert service.get_case(cid)["status"] == "returned"
    service.run_valuation(cid, "a.chen")
    with pytest.raises(service.ReviewError, match="re-run"):
        service.submit(cid, "a.chen", "Margin path supported.")
    _opine(cid, "concur")
    service.submit(cid, "a.chen", "Margin path supported.")
    service.approve(cid, "s.patel", "Approved.")
    case = service.get_case(cid)
    assert case["status"] == "approved" and case["locked"]
    with pytest.raises(service.ReviewError, match="locked"):
        service.run_valuation(cid, "a.chen")


def test_accepting_a_recommendation_applies_an_audited_input_change():
    cid = _case("D-1003", "performing")                      # Bluepeak: margin-expansion check proposes a value
    service.run_valuation(cid, "a.chen")
    service.generate_recommendations(cid, "a.chen")
    rec = next(r for r in service.recommendations(cid) if r["field"] == "m_y5")
    service.decide_recommendation(rec["id"], "edit", "a.chen", value=0.31, note="Agree in direction; 31% per plan.")
    assert service.input_values(cid)["m_y5"] == 0.31
    events = [e["event"] for e in store.audit_trail(cid)]
    assert "recommendation_applied" in events and "recommendation_edited" in events


def test_audit_log_is_append_only_and_chained():
    cid = _case()
    assert store.verify_chain()["ok"]
    with sqlite3.connect(store.db_path()) as c:
        with pytest.raises(sqlite3.DatabaseError):
            c.execute("UPDATE audit_log SET rationale = 'x' WHERE case_id = ?", (cid,))
        with pytest.raises(sqlite3.DatabaseError):
            c.execute("DELETE FROM audit_log")


def test_numguard_flags_invented_figures():
    payload = {"mid": 497.31, "vs": -0.1847, "text": "Weighted 50%"}
    assert numguard.unverified_numbers("Value of 497.3, down 18.5%, weight 50%.", payload) == []
    assert numguard.unverified_numbers("Value of 512.0 in FY2025.", payload) == ["512.0"]


def test_uploaded_template_is_sandboxed():
    cid = _case()
    service.run_valuation(cid, "a.chen")
    with pytest.raises(service.ReviewError):
        render.save_uploaded("evil.md.j2", b"{{ ''.__class__.__mro__[1].__subclasses__() }}", {"x": 1})


def test_gmail_link_never_sends():
    url = share.gmail_compose_url(["a@b.com"], [], "Subj & more", "Body\nline")
    assert url.startswith("https://mail.google.com/mail/?view=cm") and "send" not in url


def test_earnings_bridge_normalizes_ebitda_and_flows_into_multiples():
    cid = _case()
    run = service.run_valuation(cid, "a.chen")["results"]
    e = run["earnings"]
    assert e["management_adjusted"] > e["normalized"] > e["reported"]   # synergies excluded, pro forma halved
    comps = next(m for m in run["methods"] if m["method"] == "trading_comps")
    assert comps["details"]["ebitda"] == pytest.approx(e["normalized"])
    service.adjust_input(cid, "addback.A4", 1.0, "Synergies contracted and already in run-rate.", "a.chen")
    run2 = service.run_valuation(cid, "a.chen")["results"]
    assert run2["earnings"]["normalized"] == pytest.approx(e["normalized"] + 5.0)
    assert any(c["id"] == "syn_A4" for c in service.latest_run(cid)["checks"])


def test_downside_policy_and_first_line_comparison():
    cid = _case()
    r = service.run_valuation(cid, "a.chen")["results"]
    assert r["downside"]["mid"] < r["conclusion"]["mid"]
    assert {t["id"] for t in r["policy_tests"]} == {"ltv", "coverage", "ltv_downside"}
    assert {x["assumption"] for x in r["first_line_comparison"]} >= {"EBITDA used", "WACC", "Enterprise value"}
    assert r["conclusion"]["rag"] in ("green", "amber", "red")


def test_troubled_reserve_is_exposure_less_pv_of_recovery():
    cid = _case("D-2001", "troubled")
    r = service.run_valuation(cid, "a.chen")["results"]
    rv, c = r["reserve"], r["conclusion"]
    assert rv["pv_mid"] == pytest.approx(c["mid"] / 1.11 ** 1.5, abs=0.01)
    assert rv["reserve_mid"] == pytest.approx(c["bank_exposure"] - rv["pv_mid"], abs=0.01)
    assert any(x["id"] == "addback_cap" for x in service.latest_run(cid)["checks"])


def test_agent_drafts_opinion_but_analyst_decides():
    cid = _case()
    service.run_valuation(cid, "a.chen")
    d = service.draft_opinion(cid, "a.chen")
    assert d["verdict"] in ("concur", "concur_with_exceptions", "do_not_concur") and d["risks"]
    assert service.get_case(cid)["opinion"] is None                     # nothing recorded until the analyst saves
    with pytest.raises(service.ReviewError):
        service.set_opinion(cid, "a.chen", "concur_with_exceptions", "Supported in part.", [])


def test_what_if_does_not_touch_the_case_of_record():
    cid = _case()
    service.run_valuation(cid, "a.chen")
    before = service.input_values(cid)
    trail = len(store.audit_trail(cid))
    w = service.what_if(cid, {"addback.A2": 0.0, "erp": 0.065})
    assert w["what_if"]["mid"] < w["base"]["mid"]
    assert service.input_values(cid) == before and len(store.audit_trail(cid)) == trail


def test_reviewer_challenge_round_trip():
    cid = _case()
    service.run_valuation(cid, "a.chen")
    _opine(cid)
    service.submit(cid, "a.chen", "")
    with pytest.raises(service.ReviewError):
        service.send_back_with_challenges(cid, "a.chen", {"erp": 0.065}, "Use the house ERP.")   # maker cannot challenge
    n = service.send_back_with_challenges(cid, "m.reyes", {"erp": 0.065, "addback.A2": 0.0}, "Use house ERP; no run-rate pricing credit.")
    assert n == 2 and service.get_case(cid)["status"] == "returned"
    chs = service.challenges(cid)
    assert {c["field"] for c in chs} == {"erp", "addback.A2"} and chs[0]["impact"]["what_if"]["mid"] < chs[0]["impact"]["base"]["mid"]
    service.run_valuation(cid, "a.chen")
    _opine(cid)
    with pytest.raises(service.ReviewError, match="challenge"):
        service.submit(cid, "a.chen", "")
    erp = next(c for c in chs if c["field"] == "erp")
    addback = next(c for c in chs if c["field"] == "addback.A2")
    service.resolve_challenge(erp["id"], "accept", "a.chen")
    assert service.input_values(cid)["erp"] == 0.065
    with pytest.raises(service.ReviewError):
        service.resolve_challenge(addback["id"], "decline", "a.chen", "")                   # response required
    service.resolve_challenge(addback["id"], "decline", "a.chen", "Price rises are contracted from January.")
    service.run_valuation(cid, "a.chen")
    _opine(cid)
    service.submit(cid, "a.chen", "Challenges answered.")
    events = [e["event"] for e in store.audit_trail(cid)]
    assert {"challenge_raised", "challenge_applied", "challenge_accepted", "challenge_declined"} <= set(events)
