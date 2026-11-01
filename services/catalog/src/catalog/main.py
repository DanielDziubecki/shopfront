"""Catalog service: products and prices, stored in PostgreSQL."""

import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, HTTPException
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from pydantic import BaseModel

from catalog import seed
from catalog.text import normalize
from shopkit.service import create_app
from shopkit.service import run as run_app

log = logging.getLogger("catalog")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://shop:shop@localhost/catalog")
TEXT_NORMALIZATION = os.environ.get("CATALOG_TEXT_NORMALIZATION", "none")


class ProductSummary(BaseModel):
    id: str
    name: str
    price_cents: int
    categories: list[str]


class Product(ProductSummary):
    description: str


SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id          text PRIMARY KEY,
    name        text NOT NULL,
    description text NOT NULL,
    price_cents integer NOT NULL CHECK (price_cents > 0),
    categories  jsonb NOT NULL
)
"""


async def migrate(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA)
        if await conn.fetchval("SELECT count(*) FROM products") == 0:
            await conn.executemany(
                "INSERT INTO products VALUES ($1, $2, $3, $4, $5)",
                [
                    (
                        p["id"],
                        p["name"],
                        p["description"],
                        p["price_cents"],
                        json.dumps(p["categories"]),
                    )
                    for p in seed.PRODUCTS
                ],
            )
            log.info("seeded %d products", len(seed.PRODUCTS))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    AsyncPGInstrumentor().instrument()
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    await migrate(pool)
    app.state.pool = pool
    yield
    await pool.close()


app = create_app("catalog", lifespan)


@app.get("/products")
async def list_products(category: str | None = None) -> list[ProductSummary]:
    pool: asyncpg.Pool = app.state.pool
    rows = await pool.fetch("SELECT id, name, price_cents, categories FROM products ORDER BY id")
    products = [
        ProductSummary(
            id=r["id"],
            name=r["name"],
            price_cents=r["price_cents"],
            categories=json.loads(r["categories"]),
        )
        for r in rows
    ]
    if category:
        products = [p for p in products if category in p.categories]
    return products


@app.get("/products/{product_id}")
async def get_product(product_id: str) -> Product:
    pool: asyncpg.Pool = app.state.pool
    row = await pool.fetchrow("SELECT * FROM products WHERE id = $1", product_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no product {product_id}")
    return Product(
        id=row["id"],
        name=row["name"],
        description=normalize(row["description"], TEXT_NORMALIZATION),
        price_cents=row["price_cents"],
        categories=json.loads(row["categories"]),
    )


def run() -> None:
    run_app(app)
