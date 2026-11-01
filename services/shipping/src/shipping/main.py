"""Shipping service: quotes shipping cost for a destination and a basket."""

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, HTTPException
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from pydantic import BaseModel, Field

from shipping.rates import DEFAULT_RATES, Rate, quote_cents
from shopkit.service import create_app
from shopkit.service import run as run_app

log = logging.getLogger("shipping")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://shop:shop@localhost/shipping")

SCHEMA = """
CREATE TABLE IF NOT EXISTS rates (
    country        char(2) PRIMARY KEY,
    base_cents     integer NOT NULL,
    per_item_cents integer NOT NULL
)
"""


class Address(BaseModel):
    street: str
    city: str
    zip: str
    country: str = Field(min_length=2, max_length=2)


class QuoteRequest(BaseModel):
    address: Address
    item_count: int = Field(gt=0)
    subtotal_cents: int = Field(ge=0)


class Quote(BaseModel):
    cost_cents: int
    currency: str = "USD"


class Rates:
    """Connects on first use: the service stays up, and reports errors, while the DB is down."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None
        self._lock = asyncio.Lock()

    async def pool(self) -> asyncpg.Pool:
        async with self._lock:
            if self._pool is None:
                pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5, timeout=5)
                async with pool.acquire() as conn:
                    await conn.execute(SCHEMA)
                    await conn.executemany(
                        "INSERT INTO rates VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                        [(c, base, per_item) for c, (base, per_item) in DEFAULT_RATES.items()],
                    )
                self._pool = pool
            return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()


rates = Rates(DATABASE_URL)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    AsyncPGInstrumentor().instrument()
    try:
        await rates.pool()
    except (OSError, asyncpg.PostgresError) as exc:
        log.error("rates database unavailable at startup: %s", exc)
    yield
    await rates.close()


app = create_app("shipping", lifespan)


@app.post("/quotes")
async def quote(req: QuoteRequest) -> Quote:
    pool = await rates.pool()
    row = await pool.fetchrow(
        "SELECT base_cents, per_item_cents FROM rates WHERE country = $1",
        req.address.country.upper(),
    )
    if row is None:
        raise HTTPException(status_code=422, detail=f"no shipping to {req.address.country}")
    rate = Rate(base_cents=row["base_cents"], per_item_cents=row["per_item_cents"])
    return Quote(cost_cents=quote_cents(rate, req.item_count, req.subtotal_cents))


def run() -> None:
    run_app(app)
