import json

import pytest

from fulfillment.invoice import render, sign
from fulfillment.main import InvalidOrderError, parse

ORDER = {
    "order_id": "ord_1",
    "user_id": "u1",
    "email": "a@example.com",
    "lines": [{"product_id": "TENT-2P", "name": "Tent", "quantity": 2, "unit_price_cents": 1000}],
    "shipping_cents": 599,
    "total_cents": 2599,
    "transaction_id": "txn_1",
}


def test_parse_accepts_a_complete_order() -> None:
    assert parse(json.dumps(ORDER).encode())["order_id"] == "ord_1"


@pytest.mark.parametrize("body", [b"not json", b"{}", json.dumps({"order_id": "x"}).encode()])
def test_parse_rejects_malformed_orders(body: bytes) -> None:
    with pytest.raises(InvalidOrderError):
        parse(body)


def test_invoice_lists_lines_and_total() -> None:
    text = render(ORDER)

    assert "2 x Tent" in text
    assert "25.99" in text


def test_signature_is_deterministic() -> None:
    assert sign("doc", rounds=10) == sign("doc", rounds=10) != sign("other", rounds=10)
