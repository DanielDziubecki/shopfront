"""Fulfillment worker: consumes placed orders from Kafka, signs an invoice, records the order.

Offsets are committed only after an order is stored, so a crash replays orders rather than
losing them (storing is idempotent). Malformed messages go to the `orders.dlq` topic.
"""

import asyncio
import json
import logging
import os
import signal
from typing import Any

import asyncpg
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, ConsumerRecord, TopicPartition
from opentelemetry import metrics, propagate, trace
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.propagators.textmap import Getter, Setter
from opentelemetry.trace import SpanKind, Status, StatusCode

from fulfillment.invoice import render, sign
from shopkit import telemetry

log = logging.getLogger("fulfillment")

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://shop:shop@localhost/orders")
RETRY_DELAY_S = 2.0

ORDERS_TOPIC = "orders"
DEAD_LETTER_TOPIC = "orders.dlq"
CONSUMER_GROUP = "fulfillment"

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

tracer = trace.get_tracer("fulfillment")
fulfilled = metrics.get_meter("fulfillment").create_counter(
    "fulfillment.orders", description="Orders processed, by result"
)

Headers = list[tuple[str, bytes]]


class _HeaderGetter(Getter[Headers]):
    def get(self, carrier: Headers, key: str) -> list[str] | None:
        values = [v.decode() for k, v in carrier if k.lower() == key.lower()]
        return values or None

    def keys(self, carrier: Headers) -> list[str]:
        return [k for k, _ in carrier]


class _HeaderSetter(Setter[Headers]):
    def set(self, carrier: Headers, key: str, value: str) -> None:
        carrier[:] = [(k, v) for k, v in carrier if k.lower() != key.lower()]
        carrier.append((key, value.encode()))


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


async def save(pool: asyncpg.Pool, order: dict[str, Any], signature: str) -> None:
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


def _span_attributes(msg: ConsumerRecord) -> dict[str, str | int]:
    return {
        "messaging.system": "kafka",
        "messaging.operation.type": "process",
        "messaging.destination.name": msg.topic,
        "messaging.consumer.group.name": CONSUMER_GROUP,
        "messaging.destination.partition.id": str(msg.partition),
        "messaging.kafka.offset": msg.offset,
    }


async def dead_letter(producer: AIOKafkaProducer, msg: ConsumerRecord, reason: str) -> None:
    headers: Headers = [
        *list(msg.headers),
        ("dlq.reason", reason.encode()),
        ("dlq.source", f"{msg.topic}/{msg.partition}/{msg.offset}".encode()),
    ]
    propagate.inject(headers, setter=_HeaderSetter())
    await producer.send_and_wait(DEAD_LETTER_TOPIC, value=msg.value, key=msg.key, headers=headers)


async def handle(pool: asyncpg.Pool, producer: AIOKafkaProducer, msg: ConsumerRecord) -> None:
    """Process one message. Returns once the order is stored or dead-lettered."""
    parent = propagate.extract(list(msg.headers), getter=_HeaderGetter())
    while True:
        with tracer.start_as_current_span(
            f"{msg.topic} process", context=parent, kind=SpanKind.CONSUMER,
            attributes=_span_attributes(msg), record_exception=False, set_status_on_exception=False,
        ) as span:  # fmt: skip
            try:
                order = parse(msg.value or b"")
            except InvalidOrderError as exc:
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                log.error(
                    "dead-lettering malformed message %s/%d/%d: %s",
                    msg.topic, msg.partition, msg.offset, exc,
                )  # fmt: skip
                await dead_letter(producer, msg, str(exc))
                fulfilled.add(1, {"result": "dead_lettered"})
                return
            span.set_attribute("app.order_id", order["order_id"])
            try:
                signature = await asyncio.to_thread(sign, render(order))
                await save(pool, order, signature)
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                log.exception("failed to fulfill order %s, retrying", order["order_id"])
                fulfilled.add(1, {"result": "error"})
            else:
                fulfilled.add(1, {"result": "fulfilled"})
                log.info(
                    "order %s fulfilled, total %d cents", order["order_id"], order["total_cents"]
                )
                return
        await asyncio.sleep(RETRY_DELAY_S)


async def consume(
    consumer: AIOKafkaConsumer, producer: AIOKafkaProducer, pool: asyncpg.Pool
) -> None:
    async for msg in consumer:
        await handle(pool, producer, msg)
        await consumer.commit({TopicPartition(msg.topic, msg.partition): msg.offset + 1})


async def main() -> None:
    telemetry.setup("fulfillment")
    AsyncPGInstrumentor().instrument()

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA)

    consumer = AIOKafkaConsumer(
        ORDERS_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=CONSUMER_GROUP,
        client_id="fulfillment",
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP, client_id="fulfillment")
    await consumer.start()
    await producer.start()
    log.info("consuming %s as group %s", ORDERS_TOPIC, CONSUMER_GROUP)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    worker = asyncio.create_task(consume(consumer, producer, pool))
    stopper = asyncio.create_task(stop.wait())
    done, _ = await asyncio.wait({worker, stopper}, return_when=asyncio.FIRST_COMPLETED)
    for task in (worker, stopper):
        task.cancel()
    await consumer.stop()
    await producer.stop()
    await pool.close()
    if worker in done:
        worker.result()  # re-raise a consumer crash so the container restarts


def run() -> None:
    asyncio.run(main())
