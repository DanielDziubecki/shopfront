"""Server-rendered HTML. Deliberately tiny: the API is what traffic exercises."""

from html import escape
from typing import Any


def price(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def layout(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{escape(title)} · Shopfront</title>
<style>body{{font-family:system-ui,sans-serif;max-width:52rem;margin:2rem auto;padding:0 1rem}}
li{{margin:.4rem 0}} .price{{color:#555}}</style></head>
<body><h1><a href="/">Shopfront</a></h1>{body}</body></html>"""


def home(products: list[dict[str, Any]]) -> str:
    items = "".join(
        f'<li><a href="/products/{escape(p["id"])}">{escape(p["name"])}</a> '
        f'<span class="price">{price(p["price_cents"])}</span></li>'
        for p in products
    )
    return layout("Outdoor gear", f"<h2>Outdoor gear</h2><ul>{items}</ul>")


def product(p: dict[str, Any], recommended: list[dict[str, Any]]) -> str:
    recs = "".join(
        f'<li><a href="/products/{escape(r["id"])}">{escape(r["name"])}</a></li>'
        for r in recommended
    )
    body = (
        f"<h2>{escape(p['name'])}</h2><p>{escape(p['description'])}</p>"
        f'<p class="price">{price(p["price_cents"])}</p>'
        f"<h3>You may also like</h3><ul>{recs}</ul>"
    )
    return layout(p["name"], body)
