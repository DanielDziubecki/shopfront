"""Checkout service: turns a cart into a paid order and hands it to fulfillment."""

import asyncio
import logging
import os
import uuid
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager

import aio_pika
import httpx
from fastapi import FastAPI, HTTPException
from opentelemetry import metrics, trace
from opentelemetry.instrumentation.aio_pika import AioPikaInstrumentor

from checkout.models import Order, OrderLine, OrderRequest
from shopkit.service import create_app, http_client
from shopkit.service import run as run_app

log = logging.getLogger("checkout")

CART_URL = os.environ.get("CART_URL", "http://localhost:8002")
CATALOG_URL = os.environ.get("CATALOG_URL", "http://localhost:8001")
PAYMENT_URL = os.environ.get("PAYMENT_URL", "http://localhost:8003")
SHIPPING_URL = os.environ.get("SHIPPING_URL", "http://localhost:8004")
RABBITMQ_URL = os.environ.get("RABBITMQ_URL", "amqp://shop:shop@localhost/")
ORDERS_EXCHANGE = "orders"

orders_placed = metrics.get_meter("checkout").create_counter(
    "checkout.orders", description="Orders placed"
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    AioPikaInstrumentor().instrument()
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel(publisher_confirms=True)
    app.state.exchange = await channel.declare_exchange(
        ORDERS_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
    )
    yield
    await connection.close()


app = create_app("checkout", lifespan)
cart = http_client(CART_URL)
catalog = http_client(CATALOG_URL)
payment = http_client(PAYMENT_URL, timeout_s=10.0)
shipping = http_client(SHIPPING_URL)


class UpstreamError(HTTPException):
    def __init__(self, service: str, exc: httpx.HTTPError) -> None:
        log.error("%s call failed: %s", service, exc)
        super().__init__(status_code=502, detail=f"{service} unavailable")


async def call(service: str, request: Awaitable[httpx.Response]) -> httpx.Response:
    try:
        resp = await request
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code < 500:
            raise HTTPException(status_code=400, detail=exc.response.text) from exc
        raise UpstreamError(service, exc) from exc
    except httpx.HTTPError as exc:
        raise UpstreamError(service, exc) from exc
    return resp


@app.post("/orders")
async def place_order(req: OrderRequest) -> Order:
    span = trace.get_current_span()
    span.set_attribute("app.user_id", req.user_id)

    items = (await call("cart", cart.get(f"/carts/{req.user_id}"))).json()["items"]
    if not items:
        raise HTTPException(status_code=400, detail="cart is empty")

    products = await asyncio.gather(
        *(call("catalog", catalog.get(f"/products/{i['product_id']}")) for i in items)
    )
    lines = [
        OrderLine(
            product_id=item["product_id"],
            name=p.json()["name"],
            quantity=item["quantity"],
            unit_price_cents=p.json()["price_cents"],
        )
        for item, p in zip(items, products, strict=True)
    ]
    subtotal = sum(line.unit_price_cents * line.quantity for line in lines)
    item_count = sum(line.quantity for line in lines)

    quote = await call(
        "shipping",
        shipping.post(
            "/quotes",
            json={
                "address": req.address.model_dump(),
                "item_count": item_count,
                "subtotal_cents": subtotal,
            },
        ),
    )
    shipping_cents: int = quote.json()["cost_cents"]
    total = subtotal + shipping_cents

    charge = await call(
        "payment",
        payment.post(
            "/charges",
            json={"amount_cents": total, "currency": "USD", "card": req.card.model_dump()},
        ),
    )

    order = Order(
        order_id=f"ord_{uuid.uuid4().hex[:16]}",
        user_id=req.user_id,
        email=req.email,
        address=req.address,
        lines=lines,
        subtotal_cents=subtotal,
        shipping_cents=shipping_cents,
        total_cents=total,
        transaction_id=charge.json()["transaction_id"],
    )
    span.set_attribute("app.order_id", order.order_id)

    exchange: aio_pika.abc.AbstractExchange = app.state.exchange
    await exchange.publish(
        aio_pika.Message(
            body=order.model_dump_json().encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=order.order_id,
        ),
        routing_key="order.placed",
    )
    await call("cart", cart.delete(f"/carts/{req.user_id}"))

    orders_placed.add(1)
    log.info("order %s placed: %d items, total %d cents", order.order_id, item_count, total)
    return order


def run() -> None:
    run_app(app)
