"""Cart service: one Valkey hash per user, product id -> quantity."""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI
from opentelemetry.instrumentation.redis import RedisInstrumentor
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from shopkit.service import create_app
from shopkit.service import run as run_app

log = logging.getLogger("cart")

VALKEY_URL = os.environ.get("VALKEY_URL", "redis://localhost:6379/0")
CART_TTL_S = 7 * 24 * 3600


class CartItem(BaseModel):
    product_id: str
    quantity: int = Field(gt=0, le=99)


class Cart(BaseModel):
    user_id: str
    items: list[CartItem]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    RedisInstrumentor().instrument()
    store = Redis.from_url(VALKEY_URL, socket_timeout=3, socket_connect_timeout=3)
    app.state.store = store
    yield
    await store.aclose()


app = create_app("cart", lifespan)


def key(user_id: str) -> str:
    return f"cart:{user_id}"


@app.get("/carts/{user_id}")
async def get_cart(user_id: str) -> Cart:
    store: Redis = app.state.store
    raw = cast(dict[bytes, bytes], await store.hgetall(key(user_id)))  # type: ignore[misc]
    items = [CartItem(product_id=k.decode(), quantity=int(v)) for k, v in sorted(raw.items())]
    return Cart(user_id=user_id, items=items)


@app.post("/carts/{user_id}/items")
async def add_item(user_id: str, item: CartItem) -> Cart:
    store: Redis = app.state.store
    async with store.pipeline(transaction=True) as pipe:
        pipe.hincrby(key(user_id), item.product_id, item.quantity)
        pipe.expire(key(user_id), CART_TTL_S)
        await pipe.execute()
    return await get_cart(user_id)


@app.delete("/carts/{user_id}", status_code=204)
async def empty_cart(user_id: str) -> None:
    store: Redis = app.state.store
    await store.delete(key(user_id))


def run() -> None:
    run_app(app)
