"""Workflow templates (config/workflows/*.yaml)."""

from __future__ import annotations

from functools import lru_cache

import yaml

from valor.config import WORKFLOWS_DIR, engine_registry


@lru_cache(maxsize=None)
def templates() -> dict[str, dict]:
    out = {}
    for p in sorted(WORKFLOWS_DIR.glob("*.yaml")):
        t = yaml.safe_load(p.read_text())
        t["_path"] = str(p)
        out[t["id"]] = t
    return out


def template(wid: str) -> dict:
    return templates()[wid]


def method_labels(t: dict) -> list[str]:
    reg = engine_registry()
    return [reg[m["id"]]["label"] for m in t["methods"]]


def static_inputs(t: dict) -> list[dict]:
    out = []
    for g in t["input_groups"]:
        for i in g.get("inputs", []):
            out.append({**i, "group": g["id"], "group_label": g["label"]})
    return out


def suggest_workflow(risk_status: str) -> str:
    return "performing" if str(risk_status).lower() == "performing" else "troubled"
