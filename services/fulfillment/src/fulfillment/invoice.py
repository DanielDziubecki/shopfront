"""Invoice rendering and signing (CPU-bound)."""

import hashlib
import json
from typing import Any

# Key-derivation rounds for the invoice signature; about 0.3 s of CPU per invoice.
SIGNING_ROUNDS = 300_000


def render(order: dict[str, Any]) -> str:
    lines = [f"Invoice for order {order['order_id']}", ""]
    for line in order["lines"]:
        amount = line["unit_price_cents"] * line["quantity"]
        lines.append(f"{line['quantity']:>3} x {line['name']:<40} {amount / 100:>10.2f}")
    lines += [
        "",
        f"{'Shipping':<46} {order['shipping_cents'] / 100:>10.2f}",
        f"{'Total':<46} {order['total_cents'] / 100:>10.2f}",
    ]
    return "\n".join(lines)


def sign(document: str, rounds: int = SIGNING_ROUNDS) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", document.encode(), b"shopfront-invoices", rounds)
    return digest.hex()


def summary(order: dict[str, Any]) -> str:
    return json.dumps({"order_id": order["order_id"], "total_cents": order["total_cents"]})
