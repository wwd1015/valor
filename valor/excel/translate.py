"""Excel -> Python translation workflow (reviewed, tested, versioned before use).

    python -m valor.excel extract                       dump formulas + values to translations/workbook_spec.json
    python -m valor.excel propose --method dcf          Claude reads the sheet and proposes a module (vN)
    python -m valor.excel verify  --method dcf --version 1
                                                        run the proposal on the workbook's inputs, compare outputs
    python -m valor.excel approve --method dcf --version 1 --reviewer m.reyes [--activate]
                                                        a reviewer approves a verified proposal; it is copied to
                                                        valor/engine/translated/ and recorded in the registry;
                                                        --activate points config/engine.yaml at it
    python -m valor.excel status                        registry and parity of the active modules

Claude proposes code only; nothing runs in the engine until it is verified against the
workbook and approved by a named reviewer.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import re
import shutil
import sys

from valor import store
from valor.agent.runner import call, prompt_text
from valor.config import CONFIG_DIR, ROOT, TRANSLATIONS_DIR, engine_registry, user
from valor.engine import base, method_module
from valor.excel import workbook

TRANSLATED_DIR = ROOT / "valor" / "engine" / "translated"
REGISTRY = TRANSLATIONS_DIR / "registry.json"

CODE_SCHEMA = {"type": "object", "properties": {
    "code": {"type": "string", "description": "complete Python module source"},
    "notes": {"type": "string", "description": "how the sheet's logic maps to the code; ambiguities"},
    "assumptions": {"type": "array", "items": {"type": "string"}}},
    "required": ["code", "notes", "assumptions"]}


def registry() -> list[dict]:
    return json.loads(REGISTRY.read_text()) if REGISTRY.exists() else []


def _save_registry(r: list[dict]) -> None:
    TRANSLATIONS_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(r, indent=1))


def _next_version(method: str) -> int:
    d = TRANSLATIONS_DIR / method
    vs = [int(p.name[1:]) for p in d.glob("v*") if p.name[1:].isdigit()] if d.exists() else []
    return max(vs, default=0) + 1


def extract() -> str:
    spec = workbook.extract_spec()
    TRANSLATIONS_DIR.mkdir(parents=True, exist_ok=True)
    out = TRANSLATIONS_DIR / "workbook_spec.json"
    out.write_text(json.dumps(spec, indent=1, default=str))
    return str(out)


def propose(method: str) -> dict:
    reg = engine_registry()[method]
    sheet = reg["workbook_sheet"]
    spec = workbook.extract_spec(sheets=["Inputs", sheet])
    mp = workbook.mapping()[workbook.METHOD_CASE[method]]
    current = method_module(method)
    contract = inspect.getsource(base)
    input_keys = sorted(mp["inputs"].keys())
    prompt = prompt_text("translate_excel", method=method, label=reg["label"], sheet=sheet,
                         spec=json.dumps(spec, indent=1, default=str), mapping=json.dumps(mp, indent=1),
                         contract=contract, input_keys=", ".join(input_keys))

    def mock():
        # Offline: re-propose the current module so the review/verify/approve flow can be exercised.
        return {"code": inspect.getsource(current),
                "notes": "MOCK proposal (agent in mock mode): the current engine module, resubmitted for verification.",
                "assumptions": ["Mock mode: no model was called."]}

    data, meta = call("translate_excel", None, prompt, CODE_SCHEMA, mock)
    v = _next_version(method)
    d = TRANSLATIONS_DIR / method / f"v{v}"
    d.mkdir(parents=True, exist_ok=True)
    code = re.sub(r"^```(?:python)?\n|```\s*$", "", data["code"].strip()) + "\n"
    (d / "proposed.py").write_text(code)
    (d / "notes.md").write_text(f"# {reg['label']} v{v}\n\n{data['notes']}\n\n## Assumptions\n\n"
                                + "\n".join(f"- {a}" for a in data["assumptions"]) + "\n")
    m = {"method": method, "version": v, "sheet": sheet, "agent": meta, "created": store.now(),
         "sha256": hashlib.sha256(code.encode()).hexdigest(), "status": "proposed"}
    (d / "meta.json").write_text(json.dumps(m, indent=1, default=str))
    return {"dir": str(d), **m}


def verify(method: str, version: int) -> dict:
    d = TRANSLATIONS_DIR / method / f"v{version}"
    try:
        mod = workbook.load_module_file(d / "proposed.py", f"valor_translation_{method}_v{version}")
        missing = [f for f in ("run", "build_inputs") if not hasattr(mod, f)]
        if missing:
            res = {"ok": False, "error": f"module lacks {missing}", "rows": []}
        else:
            res = workbook.parity(method, mod)
    except Exception as e:  # noqa: BLE001 - a broken proposal is a failed verification
        res = {"ok": False, "error": f"{type(e).__name__}: {e}", "rows": []}
    res["verified_at"] = store.now()
    (d / "verification.json").write_text(json.dumps(res, indent=1, default=str))
    meta = json.loads((d / "meta.json").read_text())
    meta["status"] = "verified" if res["ok"] else "failed"
    (d / "meta.json").write_text(json.dumps(meta, indent=1, default=str))
    return res


def approve(method: str, version: int, reviewer: str, activate: bool = False) -> dict:
    if user(reviewer)["role"] not in ("reviewer", "admin"):
        raise SystemExit(f"{reviewer} is not a reviewer (config/users.yaml)")
    d = TRANSLATIONS_DIR / method / f"v{version}"
    ver = json.loads((d / "verification.json").read_text()) if (d / "verification.json").exists() else {}
    if not ver.get("ok"):
        raise SystemExit("verify the proposal against the workbook first (it must pass)")
    meta = json.loads((d / "meta.json").read_text())
    code = (d / "proposed.py").read_text()
    if hashlib.sha256(code.encode()).hexdigest() != meta["sha256"]:
        raise SystemExit("proposed.py changed after it was proposed; re-propose or re-verify")
    TRANSLATED_DIR.mkdir(parents=True, exist_ok=True)
    (TRANSLATED_DIR / "__init__.py").touch()
    target = TRANSLATED_DIR / f"{method}_v{version}.py"
    shutil.copy(d / "proposed.py", target)
    module = f"valor.engine.translated.{method}_v{version}"
    entry = {"method": method, "version": version, "module": module, "sha256": meta["sha256"], "approved_by": reviewer,
             "approved_at": store.now(), "verification": {"ok": True, "rows": ver["rows"]}, "agent": meta.get("agent", {}).get("mode")}
    r = registry()
    r.append(entry)
    _save_registry(r)
    meta["status"] = "approved"
    (d / "meta.json").write_text(json.dumps(meta, indent=1, default=str))
    if activate:
        path = CONFIG_DIR / "engine.yaml"
        text = path.read_text()
        text = re.sub(rf"(\n  {method}:\n(?:    .*\n)*?    module: )\S+", rf"\g<1>{module}", text)
        path.write_text(text)
        engine_registry.cache_clear()
        entry["activated"] = True
    return entry


def proposals() -> list[dict]:
    out = []
    for p in sorted(TRANSLATIONS_DIR.glob("*/v*/meta.json")):
        m = json.loads(p.read_text())
        v = p.parent / "verification.json"
        m["verification"] = json.loads(v.read_text()) if v.exists() else None
        out.append(m)
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m valor.excel", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("extract")
    p = sub.add_parser("propose")
    p.add_argument("--method", required=True, choices=list(engine_registry()))
    for name in ("verify", "approve"):
        p = sub.add_parser(name)
        p.add_argument("--method", required=True, choices=list(engine_registry()))
        p.add_argument("--version", required=True, type=int)
        if name == "approve":
            p.add_argument("--reviewer", required=True)
            p.add_argument("--activate", action="store_true")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    if a.cmd == "extract":
        print(extract())
    elif a.cmd == "propose":
        print(json.dumps(propose(a.method), indent=1, default=str))
    elif a.cmd == "verify":
        res = verify(a.method, a.version)
        print(json.dumps(res, indent=1, default=str))
        sys.exit(0 if res["ok"] else 1)
    elif a.cmd == "approve":
        print(json.dumps(approve(a.method, a.version, a.reviewer, a.activate), indent=1))
    elif a.cmd == "status":
        for m in engine_registry():
            res = workbook.parity(m)
            print(f"{m:15} {res['module']:40} parity {'OK' if res['ok'] else 'FAIL'}")
        print(json.dumps(registry(), indent=1))
