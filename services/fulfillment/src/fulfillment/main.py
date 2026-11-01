"""Fulfillment worker: consumes `order.placed` events, signs an invoice, records the order."""

import asyncio
import json
import logging
import os
import signal
from typing import Any

import aio_pika
import asyncpg
from opentelemetry import metrics
from opentelemetry.instrumentation.aio_pika import AioPikaInstrumentor
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor

from fulfillment.invoice import render, sign
from shopkit import telemetry

log = logging.getLogger("fulfillment")

RABBITMQ_URL = os.environ.get("RABBITMQ_URL", "amqp://shop:shop@localhost/")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://shop:shop@localhost/orders")
PREFETCH = int(os.environ.get("FULFILLMENT_PREFETCH", "10"))

ORDERS_EXCHANGE = "orders"
QUEUE = "fulfillment.orders"
DEAD_LETTER_EXCHANGE = "orders.dlx"
DEAD_LETTER_QUEUE = "fulfillment.orders.dead"

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    order_id       text PRIMARY KEY,
    user_id        text NOT NULL,
    email          text NOT NULL,
    total_cents    integer NOT NULL,
    transaction_id text NOT NULL,
    invoice_sig    text NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS order_lines (
    order_id         text NOT NULL REFERENCES orders ON DELETE CASCADE,
    product_id       text NOT NULL,
    quantity         integer NOT NULL,
    unit_price_cents integer NOT NULL,
    PRIMARY KEY (order_id, product_id)
);
"""

fulfilled = metrics.get_meter("fulfillment").create_counter(
    "fulfillment.orders", description="Orders processed, by result"
)


class InvalidOrderError(Exception):
    pass


REQUIRED_FIELDS = ("order_id", "user_id", "email", "lines", "total_cents", "transaction_id")


def parse(body: bytes) -> dict[str, Any]:
    try:
        order = json.loads(body)
    except ValueError as exc:
        raise InvalidOrderError(f"not JSON: {exc}") from exc
    if not isinstance(order, dict):
        raise InvalidOrderError("not an object")
    missing = [field for field in REQUIRED_FIELDS if field not in order]
    if missing:
        raise InvalidOrderError(f"missing fields: {', '.join(missing)}")
    return order


async def record(pool: asyncpg.Pool, order: dict[str, Any], signature: str) -> None:
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO orders"
            " (order_id, user_id, email, total_cents, transaction_id, invoice_sig)"
            " VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT DO NOTHING",
            order["order_id"],
            order["user_id"],
            order["email"],
            order["total_cents"],
            order["transaction_id"],
            signature,
        )
        await conn.executemany(
            "INSERT INTO order_lines VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
            [
                (order["order_id"], line["product_id"], line["quantity"], line["unit_price_cents"])
                for line in order["lines"]
            ],
        )


async def handle(pool: asyncpg.Pool, message: aio_pika.abc.AbstractIncomingMessage) -> None:
    try:
        order = parse(message.body)
    except InvalidOrderError as exc:
        log.error("rejecting malformed order message %s: %s", message.message_id, exc)
        fulfilled.add(1, {"result": "rejected"})
        await message.reject(requeue=False)
        return
    try:
        signature = await asyncio.to_thread(sign, render(order))
        await record(pool, order, signature)
    except Exception:
        log.exception("failed to fulfill order %s, requeueing", order["order_id"])
        fulfilled.add(1, {"result": "error"})
        await asyncio.sleep(1)
        await message.nack(requeue=True)
        return
    await message.ack()
    fulfilled.add(1, {"result": "fulfilled"})
    log.info("order %s fulfilled, total %d cents", order["order_id"], order["total_cents"])


async def main() -> None:
    telemetry.setup("fulfillment")
    AioPikaInstrumentor().instrument()
    AsyncPGInstrumentor().instrument()

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA)

    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=PREFETCH)
    orders = await channel.declare_exchange(
        ORDERS_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
    )
    dlx = await channel.declare_exchange(
        DEAD_LETTER_EXCHANGE, aio_pika.ExchangeType.FANOUT, durable=True
    )
    dead = await channel.declare_queue(DEAD_LETTER_QUEUE, durable=True)
    await dead.bind(dlx)
    queue = await channel.declare_queue(
        QUEUE, durable=True, arguments={"x-dead-letter-exchange": DEAD_LETTER_EXCHANGE}
    )
    await queue.bind(orders, routing_key="order.placed")

    await queue.consume(lambda message: handle(pool, message))
    log.info("consuming %s with prefetch %d", QUEUE, PREFETCH)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    await connection.close()
    await pool.close()


def run() -> None:
    asyncio.run(main())
