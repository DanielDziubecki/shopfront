from shipping.rates import FREE_SHIPPING_FROM_CENTS, Rate, quote_cents

RATE = Rate(base_cents=599, per_item_cents=150)


def test_first_item_pays_the_base_fee() -> None:
    assert quote_cents(RATE, item_count=1, subtotal_cents=1000) == 599


def test_each_extra_item_adds_a_fee() -> None:
    assert quote_cents(RATE, item_count=3, subtotal_cents=1000) == 599 + 2 * 150


def test_large_orders_ship_free() -> None:
    assert quote_cents(RATE, item_count=3, subtotal_cents=FREE_SHIPPING_FROM_CENTS) == 0
