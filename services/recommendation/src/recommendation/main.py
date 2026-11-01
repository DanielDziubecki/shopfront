"""Recommendation service: "you may also like" for a product."""

import logging
import os
import time
from typing import Annotated

from fastapi import HTTPException, Query
from opentelemetry import metrics
from pydantic import BaseModel

from recommendation.similarity import Item, VectorCache, rank
from shopkit.service import create_app, http_client
from shopkit.service import run as run_app

log = logging.getLogger("recommendation")

CATALOG_URL = os.environ.get("CATALOG_URL", "http://localhost:8001")
CATALOG_TTL_S = 60

app = create_app("recommendation")
catalog = http_client(CATALOG_URL)
cache = VectorCache(mode=os.environ.get("RECOMMENDATION_CACHE", "v1"))
_catalog_items: tuple[float, list[Item]] = (0.0, [])

metrics.get_meter("recommendation").create_observable_gauge(
    "recommendation.cache.entries",
    callbacks=[lambda _: [metrics.Observation(len(cache))]],
    description="Entries in the feature vector cache",
)


class Recommendations(BaseModel):
    product_id: str
    product_ids: list[str]


async def catalog_items() -> list[Item]:
    global _catalog_items
    fetched_at, items = _catalog_items
    if time.monotonic() - fetched_at > CATALOG_TTL_S or not items:
        resp = await catalog.get("/products")
        resp.raise_for_status()
        items = [Item(id=p["id"], categories=tuple(p["categories"])) for p in resp.json()]
        _catalog_items = (time.monotonic(), items)
    return items


@app.get("/recommendations")
async def recommendations(
    product_id: str,
    session_id: str = "anonymous",
    limit: Annotated[int, Query(ge=1, le=10)] = 4,
) -> Recommendations:
    items = await catalog_items()
    if product_id not in {i.id for i in items}:
        raise HTTPException(status_code=404, detail=f"no product {product_id}")
    vectors = cache.vectors(items, session_id, product_id)
    return Recommendations(product_id=product_id, product_ids=rank(product_id, vectors, limit))


def run() -> None:
    run_app(app)
