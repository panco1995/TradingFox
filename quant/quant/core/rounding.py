"""Order price/quantity rounding.

Exchanges reject orders that violate tick size, step size or minimum notional.
Always round *before* sending: retrying a rejected order wastes rate-limit
budget and can leave the strategy in an inconsistent state.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation

Number = int | float | str | Decimal


def to_decimal(value: Number) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:  # pragma: no cover - defensive
        raise ValueError(f"not a number: {value!r}") from exc


def round_step(value: Number, step: Number, mode: str = "down") -> Decimal:
    """Round `value` onto a grid of `step`.

    mode: "down" (floor, safe for quantities) or "nearest" (half-up, for prices).
    """
    if mode not in {"down", "nearest"}:
        raise ValueError(f"unknown mode: {mode}")
    step_d = to_decimal(step)
    if step_d <= 0:
        raise ValueError("step must be positive")
    value_d = to_decimal(value)
    rounding = ROUND_DOWN if mode == "down" else ROUND_HALF_UP
    steps = (value_d / step_d).to_integral_value(rounding=rounding)
    return (steps * step_d).quantize(step_d)


def floor_qty(qty: Number, step_size: Number) -> Decimal:
    return round_step(qty, step_size, mode="down")


def round_price(price: Number, tick_size: Number) -> Decimal:
    return round_step(price, tick_size, mode="nearest")


def check_order(
    price: Number,
    qty: Number,
    tick_size: Number,
    step_size: Number,
    min_notional: Number | None = None,
) -> tuple[bool, str]:
    """Return (ok, reason). Reason is empty when the order is valid."""
    price_d = to_decimal(price)
    qty_d = to_decimal(qty)

    if price_d <= 0:
        return False, "price must be positive"
    if qty_d <= 0:
        return False, "qty must be positive"

    if round_price(price_d, tick_size) != price_d:
        return False, f"price {price_d} not aligned to tick {tick_size}"
    if floor_qty(qty_d, step_size) != qty_d:
        return False, f"qty {qty_d} not aligned to step {step_size}"

    if min_notional is not None and price_d * qty_d < to_decimal(min_notional):
        return False, f"notional {price_d * qty_d} below minimum {min_notional}"

    return True, ""


def build_order(
    price: Number,
    qty: Number,
    tick_size: Number,
    step_size: Number,
    min_notional: Number | None = None,
) -> tuple[Decimal, Decimal] | None:
    """Round price/qty into a valid order, or None if it cannot be made valid."""
    price_d = round_price(price, tick_size)
    qty_d = floor_qty(qty, step_size)
    ok, _ = check_order(price_d, qty_d, tick_size, step_size, min_notional)
    return (price_d, qty_d) if ok else None
