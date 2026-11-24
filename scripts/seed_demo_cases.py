"""Create demo cases in different states (uses the mock agent, so no Claude calls).

    python scripts/seed_demo_cases.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("VALOR_AGENT_MODE", "mock")

from valor import service  # noqa: E402
from valor.report import render  # noqa: E402


def main():
    # 1. Approved troubled case with an adjustment and decided recommendations
    c1 = service.create_case("D-2001", "troubled", "a.chen")
    service.pull_data(c1, "a.chen")
    service.adjust_input(c1, "rr_inventory_high", 0.55, "Aged industrial inventory; Q3 appraisal supports a lower high case.", "a.chen")
    service.run_valuation(c1, "a.chen")
    service.generate_recommendations(c1, "a.chen")
    for r in service.recommendations(c1):
        service.decide_recommendation(r["id"], "reject", "a.chen", note="Noted; addressed in the memo commentary.")
    service.set_opinion(c1, "a.chen", "concur_with_exceptions",
                        "Recovery supports a reserve, but the first line's estimate leans on add-backs above the policy cap.",
                        ["Exclude the expected customer re-win from recovery EBITDA", "Obtain a fresh inventory appraisal"])
    service.submit(c1, "a.chen", "Recovery view below first line; inventory haircut applied.")
    service.approve(c1, "m.reyes", "Agree with the recovery estimate.")
    render.generate(c1, "credit_memo.md.j2", "m.reyes", use_agent=False)

    # 2. Performing case submitted and awaiting review
    c2 = service.create_case("D-1001", "performing", "j.okafor")
    service.pull_data(c2, "j.okafor")
    service.adjust_input(c2, "g_y1", 0.06, "Year-1 growth haircut toward the two-year historical CAGR.", "j.okafor")
    service.run_valuation(c2, "j.okafor")
    service.set_opinion(c2, "j.okafor", "concur_with_exceptions",
                        "Collateral coverage holds in the downside case, but the first line's EV relies on unrealized synergies.",
                        ["Exclude CrossDock synergies from collateral EBITDA", "Support the 9.0% WACC"])
    service.submit(c2, "j.okafor", "First line looks rich versus our DCF.")

    # 3. Performing case in draft with data pulled
    c3 = service.create_case("D-1003", "performing", "a.chen")
    service.pull_data(c3, "a.chen")
    service.run_valuation(c3, "a.chen")
    print("created", c1, c2, c3)


if __name__ == "__main__":
    main()
