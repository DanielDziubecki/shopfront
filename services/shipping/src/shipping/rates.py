"""Shipping cost calculation."""

from dataclasses import dataclass

# country -> (base fee, fee per item), in cents
DEFAULT_RATES: dict[str, tuple[int, int]] = {
    "US": (599, 150),
    "CA": (899, 200),
    "GB": (999, 250),
    "DE": (899, 200),
    "PL": (799, 150),
    "AU": (1499, 300),
}
FREE_SHIPPING_FROM_CENTS = 15000


@dataclass(frozen=True)
class Rate:
    base_cents: int
    per_item_cents: int


def quote_cents(rate: Rate, item_count: int, subtotal_cents: int) -> int:
    if subtotal_cents >= FREE_SHIPPING_FROM_CENTS:
        return 0
    return rate.base_cents + rate.per_item_cents * max(item_count - 1, 0)
