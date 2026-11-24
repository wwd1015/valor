"""Recovery waterfall by creditor class: absolute priority, pro rata within a priority level."""

from __future__ import annotations

from itertools import groupby


def run(distributable: float, claims: list[dict]) -> dict:
    """claims: [{claim_id, claim_class, priority, amount, bank_share}] -> per-claim recoveries."""
    remaining = max(0.0, distributable)
    out = []
    ordered = sorted(claims, key=lambda c: (c["priority"], c["claim_id"]))
    for _, group in groupby(ordered, key=lambda c: c["priority"]):
        group = list(group)
        total = sum(c["amount"] for c in group)
        paid_total = min(remaining, total)
        for c in group:
            paid = paid_total * (c["amount"] / total) if total else 0.0
            out.append({**c, "recovered": round(paid, 4),
                        "recovery_pct": round(paid / c["amount"], 4) if c["amount"] else 0.0})
        remaining -= paid_total
    bank_claim = sum(c["amount"] * c["bank_share"] for c in out)
    bank_recovered = sum(c["recovered"] * c["bank_share"] for c in out)
    return {
        "distributable": round(distributable, 4),
        "claims": out,
        "residual_to_equity": round(remaining, 4),
        "bank_claim": round(bank_claim, 4),
        "bank_recovered": round(bank_recovered, 4),
        "bank_recovery_pct": round(bank_recovered / bank_claim, 4) if bank_claim else 0.0,
    }
