"""Storefront: the only public service. Renders pages and fronts the JSON API."""

import logging
import os
from typing import Annotated, Any

import httpx
from fastapi import Body, Header, HTTPException
from fastapi.responses import HTMLResponse

from shopkit.service import create_app, http_client
from shopkit.service import run as run_app
from storefront import pages

log = logging.getLogger("storefront")

# Each simulated shopper (or browser) identifies its session with an X-Session-Id header.
SessionId = Annotated[str, Header(alias="x-session-id")]


CATALOG_URL = os.environ.get("CATALOG_URL", "http://localhost:8001")
CART_URL = os.environ.get("CART_URL", "http://localhost:8002")
CHECKOUT_URL = os.environ.get("CHECKOUT_URL", "http://localhost:8005")
RECOMMENDATION_URL = os.environ.get("RECOMMENDATION_URL", "http://localhost:8006")

app = create_app("storefront")
catalog = http_client(CATALOG_URL)
cart = http_client(CART_URL)
checkout = http_client(CHECKOUT_URL, timeout_s=20.0)
recommendation = http_client(RECOMMENDATION_URL, timeout_s=2.0)


async def fetch(client: httpx.AsyncClient, method: str, path: str, **kwargs: Any) -> Any:
    """Call a backend and pass its client errors through; anything else becomes a 502."""
    try:
        resp = await client.request(method, path, **kwargs)
    except httpx.HTTPError as exc:
        log.error("%s %s%s failed: %s", method, client.base_url, path, exc)
        raise HTTPException(status_code=502, detail="upstream unavailable") from exc
    if resp.status_code >= 500:
        log.error("%s %s%s returned %d", method, client.base_url, path, resp.status_code)
        raise HTTPException(status_code=502, detail="upstream error")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail"))
    return resp.json() if resp.content else None


async def recommended_for(product_id: str, session_id: str) -> list[str]:
    """Recommendations are optional: on failure the page renders without them."""
    try:
        resp = await recommendation.get(
            "/recommendations", params={"product_id": product_id, "session_id": session_id}
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("recommendations unavailable for %s: %s", product_id, exc)
        return []
    return resp.json()["product_ids"]


async def product_view(product_id: str, session_id: str) -> dict[str, Any]:
    product = await fetch(catalog, "GET", f"/products/{product_id}")
    ids = await recommended_for(product_id, session_id)
    summaries = {p["id"]: p for p in await fetch(catalog, "GET", "/products")}
    return {**product, "recommendations": [summaries[i] for i in ids if i in summaries]}


@app.get("/", response_class=HTMLResponse)
async def home() -> str:
    return pages.home(await fetch(catalog, "GET", "/products"))


@app.get("/products/{product_id}", response_class=HTMLResponse)
async def product_page(product_id: str, session_id: SessionId = "web") -> str:
    view = await product_view(product_id, session_id)
    return pages.product(view, view["recommendations"])


@app.get("/api/products")
async def api_products(category: str | None = None) -> Any:
    params = {"category": category} if category else None
    return await fetch(catalog, "GET", "/products", params=params)


@app.get("/api/products/{product_id}")
async def api_product(product_id: str, session_id: SessionId = "web") -> Any:
    return await product_view(product_id, session_id)


@app.get("/api/cart")
async def api_cart(session_id: SessionId) -> Any:
    return await fetch(cart, "GET", f"/carts/{session_id}")


@app.post("/api/cart")
async def api_add_to_cart(
    session_id: SessionId,
    product_id: Annotated[str, Body()],
    quantity: Annotated[int, Body()] = 1,
) -> Any:
    await fetch(catalog, "GET", f"/products/{product_id}")
    return await fetch(
        cart,
        "POST",
        f"/carts/{session_id}/items",
        json={"product_id": product_id, "quantity": quantity},
    )


@app.post("/api/checkout")
async def api_checkout(session_id: SessionId, details: Annotated[dict[str, Any], Body()]) -> Any:
    return await fetch(checkout, "POST", "/orders", json={**details, "user_id": session_id})


def run() -> None:
    run_app(app)
