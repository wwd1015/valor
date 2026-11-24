"""Paths and config loading. All tunable assumptions live in config/*.yaml."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
WORKFLOWS_DIR = CONFIG_DIR / "workflows"
TEMPLATES_DIR = ROOT / "templates" / "reports"
PROMPTS_DIR = ROOT / "prompts"
MOCK_DATA_DIR = ROOT / "data" / "mock"
WORKBOOK_PATH = ROOT / "workbook" / "master_valuation.xlsx"
TRANSLATIONS_DIR = ROOT / "translations"


def _load(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=None)
def settings() -> dict:
    s = _load(CONFIG_DIR / "settings.yaml")
    # environment overrides, handy for tests and demos
    if os.environ.get("VALOR_AGENT_MODE"):
        s["agent"]["mode"] = os.environ["VALOR_AGENT_MODE"]
    if os.environ.get("VALOR_CLAUDE_BIN"):
        s["agent"]["claude_bin"] = os.environ["VALOR_CLAUDE_BIN"]
    if os.environ.get("VALOR_DB"):
        s["storage"]["sqlite_path"] = os.environ["VALOR_DB"]
    return s


def path_setting(*keys: str) -> Path:
    v = settings()
    for k in keys:
        v = v[k]
    p = Path(v)
    return p if p.is_absolute() else ROOT / p


@lru_cache(maxsize=None)
def users() -> list[dict]:
    return _load(CONFIG_DIR / "users.yaml")["users"]


def user(uid: str) -> dict:
    for u in users():
        if u["id"] == uid:
            return u
    return {"id": uid, "name": uid, "role": "analyst", "title": ""}


@lru_cache(maxsize=None)
def engine_registry() -> dict:
    return _load(CONFIG_DIR / "engine.yaml")["methods"]


@lru_cache(maxsize=None)
def table_map() -> dict:
    return _load(path_setting("data", "tables"))["tables"]
