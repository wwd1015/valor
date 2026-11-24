"""Shared types for valuation methods.

Contract for a method module (see config/engine.yaml):
    VERSION: str
    build_inputs(values: dict[str, float], claims: list[dict]) -> <Inputs dataclass>
    run(inputs) -> MethodResult
All figures are USD millions. No method ever calls a model: numbers come from here only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class MethodResult:
    method: str
    label: str
    low: float
    mid: float
    high: float
    measure: str = "enterprise_value"         # enterprise_value | bank_recovery
    details: dict[str, Any] = field(default_factory=dict)
    version: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def r2(x: float) -> float:
    return round(float(x), 2)
