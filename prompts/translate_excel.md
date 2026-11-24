Translate the "$sheet" sheet of the bank's master valuation workbook into a Python module that
implements the $label method ("$method") for Valor's deterministic valuation engine.

Requirements:
- Reproduce the workbook's logic exactly, formula for formula. Do not "improve" the method;
  if a formula looks wrong, reproduce it and say so in `notes`.
- The module must define `VERSION` (a string), `build_inputs(values: dict, claims: list[dict] | None = None)`
  and `run(inputs) -> MethodResult`, following the contract below. Import `MethodResult` and
  `r2` from `valor.engine.base`. Use only the standard library.
- `values` holds the engine inputs keyed as in the cell map below (input key -> workbook cell).
  Claims for recovery methods arrive as `claims` (claim_id, claim_class, priority, bank_share)
  with amounts in `values["claim.<claim_id>"]`.
- `run` returns low, mid and high (USD millions) matching the workbook output cells in the map,
  plus useful intermediate figures in `details`.
- Include a module docstring naming the sheet and the cells each output comes from.

Engine input keys: $input_keys

Contract (valor/engine/base.py):
```python
$contract
```

Cell map for this workbook (inputs and the outputs your code must reproduce):
```json
$mapping
```

Sheet contents (cell, row label, formula or constant, and the workbook's calculated value):
```json
$spec
```
