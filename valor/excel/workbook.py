"""Read the master workbook: recalculate its formulas (the `formulas` package, no Excel needed),
and compare engine modules against the workbook's own outputs."""

from __future__ import annotations

import importlib.util
import re
from functools import lru_cache
from pathlib import Path
from types import ModuleType

import yaml
from openpyxl import load_workbook

from valor.config import ROOT, WORKBOOK_PATH

MAPPING_PATH = ROOT / "workbook" / "mapping.yaml"
KEY = re.compile(r"^'?\[[^\]]+\](?P<sheet>[^']+)'?!(?P<cell>[A-Z]+\d+)$")


def mapping() -> dict:
    return yaml.safe_load(MAPPING_PATH.read_text())


@lru_cache(maxsize=4)
def _calculate(path: str, mtime: float) -> dict[str, float]:
    import formulas  # imported lazily: slow to import
    model = formulas.ExcelModel().loads(path).finish()
    sol = model.calculate()
    out = {}
    for k, v in sol.items():
        m = KEY.match(k)
        if not m:
            continue
        try:
            out[f"{m['sheet'].upper()}!{m['cell']}"] = float(v.value[0][0])
        except (TypeError, ValueError, IndexError):
            pass
    return out


def calculated(path: Path = WORKBOOK_PATH) -> dict[str, float]:
    return _calculate(str(path), path.stat().st_mtime)


def cell(cells: dict, ref: str) -> float:
    sheet, addr = ref.split("!")
    return cells[f"{sheet.upper()}!{addr.replace('$', '')}"]


def workbook_cases(cells: dict | None = None) -> dict:
    """Engine inputs and expected outputs for the workbook's sample cases."""
    cells = cells or calculated()
    mp = mapping()
    out = {}
    for wf, spec in mp.items():
        values = {k: cell(cells, ref) for k, ref in spec["inputs"].items()}
        claims = []
        for c in spec.get("claims", []):
            values[f"claim.{c['claim_id']}"] = cell(cells, c["amount_cell"])
            claims.append({k: c[k] for k in ("claim_id", "claim_class", "priority", "bank_share")})
        expected = {k: cell(cells, ref) for k, ref in spec["outputs"].items()}
        out[wf] = {"values": values, "claims": claims, "expected": expected}
    return out


METHOD_CASE = {"dcf": "performing", "trading_comps": "performing", "precedents": "performing",
               "liquidation": "troubled", "distressed_gc": "troubled"}


def load_module_file(path: Path, name: str = "valor_candidate") -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[name] = mod          # dataclasses need the module registered
    spec.loader.exec_module(mod)
    return mod


def parity(method: str, module: ModuleType | None = None, tol: float = 0.01) -> dict:
    """Run `module` (default: the registered engine module) on the workbook's inputs and compare."""
    if module is None:
        from valor.engine import method_module
        module = method_module(method)
    case = workbook_cases()[METHOD_CASE[method]]
    res = module.run(module.build_inputs(case["values"], case["claims"]))
    rows = []
    for side in ("low", "mid", "high"):
        key = f"{method}.{side}"
        if key in case["expected"]:
            exp, got = case["expected"][key], getattr(res, side)
            rows.append({"output": key, "workbook": round(exp, 4), "engine": round(got, 4),
                         "diff": round(got - exp, 4), "ok": abs(got - exp) <= tol})
    return {"method": method, "module": module.__name__, "version": getattr(module, "VERSION", "?"),
            "ok": all(r["ok"] for r in rows) and bool(rows), "rows": rows, "tolerance": tol}


def extract_spec(path: Path = WORKBOOK_PATH, sheets: list[str] | None = None) -> dict:
    """Formulas and constants per sheet, with row labels: what Claude reads to translate."""
    wb = load_workbook(path, data_only=False)
    cells = calculated(path)
    spec = {}
    for ws in wb.worksheets:
        if sheets and ws.title not in sheets:
            continue
        items = []
        for row in ws.iter_rows():
            label = next((str(c.value) for c in row[:2] if isinstance(c.value, str) and not str(c.value).startswith("=")), "")
            for c in row:
                if c.value is None:
                    continue
                v = c.value
                entry = {"cell": c.coordinate, "label": label}
                if isinstance(v, str) and v.startswith("="):
                    entry["formula"] = v
                    entry["value"] = cells.get(f"{ws.title.upper()}!{c.coordinate}")
                else:
                    entry["value"] = v
                items.append(entry)
        spec[ws.title] = items
    return spec
