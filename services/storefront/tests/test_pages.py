from storefront import pages


def test_home_lists_products_with_prices() -> None:
    html = pages.home([{"id": "TENT-2P", "name": "Tent", "price_cents": 24900}])

    assert 'href="/products/TENT-2P"' in html
    assert "$249.00" in html


def test_product_names_are_escaped() -> None:
    html = pages.product(
        {"name": "<b>Tent</b>", "description": "d", "price_cents": 100}, recommended=[]
    )

    assert "&lt;b&gt;Tent&lt;/b&gt;" in html
    assert "<b>Tent</b>" not in html
