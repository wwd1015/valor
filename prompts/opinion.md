Draft the second-line opinion on the first line's valuation, for the analyst to edit.

- verdict: "concur" (second-line view supports the first line's value), "concur_with_exceptions"
  (supports it subject to the listed conditions), or "do_not_concur" (the first line's value is not
  supported). Weigh the traffic light on variance (`conclusion.rag`), the policy tests, the
  earnings bridge and the checks. `rule_based_suggestion` is the deterministic suggestion; you may
  disagree if the evidence warrants it.
- rationale: two or three sentences an approver can rely on.
- conditions: concrete conditions or exceptions (empty if concur).
- risks: the top three risks to the collateral value, each with a mitigant.
- questions: up to five questions back to the first line (the deal team), specific enough to answer.

Quote only figures that appear in the payload.

```json
$payload
```
