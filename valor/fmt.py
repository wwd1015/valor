"""Number formatting shared by the UI and reports."""

from __future__ import annotations

UNIT_LABEL = {"musd": "USD m", "pct": "%", "x": "x", "num": ""}


def fmt(v, unit: str = "musd", signed: bool = False) -> str:
    if v is None or v == "":
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    s = "+" if signed and v > 0 else ""
    if unit == "pct":
        t = f"{v * 100:.2f}".rstrip("0").rstrip(".")
        return f"{s}{t}%"
    if unit == "x":
        return f"{s}{v:.1f}x"
    if unit == "num":
        return f"{s}{v:.2f}"
    return f"{s}{v:,.1f}"


def money(v) -> str:
    return fmt(v, "musd")


def pct(v, signed: bool = False) -> str:
    if v is None:
        return "—"
    return f"{'+' if signed and v > 0 else ''}{v * 100:.1f}%"


def parse_input(text: str, unit: str) -> float:
    """Parse a user-typed value in display units: 7.5 (%) -> 0.075, '12.5x' -> 12.5, '1,234' -> 1234."""
    t = str(text).strip().replace(",", "").rstrip("x").rstrip("%").strip()
    v = float(t)
    return v / 100 if unit == "pct" else v


def display_value(v, unit: str) -> str:
    """The value as the user would type it back."""
    if v is None:
        return ""
    return f"{v * 100:.4g}" if unit == "pct" else f"{v:.6g}"
