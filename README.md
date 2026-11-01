# Shopfront

[![stack](https://github.com/DanielDziubecki/shopfront/actions/workflows/stack.yml/badge.svg)](https://github.com/DanielDziubecki/shopfront/actions/workflows/stack.yml)

An online outdoor-gear store built from small Python services, fully instrumented with OpenTelemetry, with an open-source observability stack and service-level alerts.

## Architecture

```
loadgen ──HTTP──▶ storefront ─┬─▶ catalog ────────▶ PostgreSQL (catalog)
                              ├─▶ recommendation ─▶ catalog
                              ├─▶ cart ───────────▶ Valkey
                              └─▶ checkout ─┬─▶ cart, catalog
                                            ├─▶ shipping ─▶ PostgreSQL (shipping)
                                            ├─▶ payment
                                            └─▶ Kafka topic "orders" (3 partitions, keyed by user)
                                                  │
                                                  ▼ consumer group "fulfillment"
                                               fulfillment ─▶ PostgreSQL (orders)
                                                  │ malformed messages
                                                  ▼
                                               Kafka topic "orders.dlq"
```

| Service | Does | Depends on |
| --- | --- | --- |
| storefront | Public HTML pages and JSON API (port 8080) | catalog, cart, checkout, recommendation |
| catalog | Products, descriptions and prices | PostgreSQL (`catalog`) |
| cart | Shopping carts | Valkey |
| checkout | Prices the cart, quotes shipping, charges the card, publishes the order | cart, catalog, shipping, payment, Kafka |
| payment | Validates and charges cards (tokenized, internal provider) | |
| shipping | Shipping quotes from per-country rate tables | PostgreSQL (`shipping`) |
| recommendation | "You may also like" from product similarity | catalog |
| fulfillment | Worker: consumes orders, signs invoices, records orders; dead-letters malformed messages | Kafka, PostgreSQL (`orders`) |
| loadgen | Simulated shoppers browsing, adding to cart and checking out | storefront |

All services are FastAPI apps (fulfillment is a plain asyncio Kafka consumer) in one [uv](https://docs.astral.sh/uv/) workspace. Shared plumbing lives in [`libs/shopkit`](libs/shopkit): OpenTelemetry setup, JSON logging with trace ids, the app factory and HTTP clients. Every service builds from the same [`Dockerfile`](Dockerfile).

## Observability (stack A)

Services send traces, metrics and logs over OTLP to the OpenTelemetry Collector, which forwards them to:

| Signal | Backend | Notes |
| --- | --- | --- |
| Traces | Tempo | HTTP, PostgreSQL, Valkey and Kafka calls are traced end to end, across the topic too. Tempo's metrics generator adds service-graph metrics. |
| Metrics | Prometheus | Request rate, errors and latency per service from the collector's span metrics connector; container CPU, memory and restarts from Docker; Kafka (including consumer lag), PostgreSQL and Valkey metrics from collector receivers; a few business metrics (orders, charges). |
| Logs | Loki | JSON logs with trace and span ids; `service_name` label |
| Alerts | Prometheus rules → Alertmanager | Shown in Grafana under Alerting |
| Dashboards | Grafana | "Shopfront services" dashboard; data sources linked trace ↔ logs ↔ metrics |

Configuration lives in [`observability/stack-a/`](observability/stack-a/).

## Alerts

Symptom-based, service-level alerts ([`alerts/slo.rules.yml`](alerts/slo.rules.yml)):

| Alert | Fires when | Severity |
| --- | --- | --- |
| StorefrontErrorRateHigh | over 5% of storefront requests fail for 1 min | page |
| StorefrontLatencyHigh | storefront p95 over 1 s for 2 min | page |
| CheckoutErrorRateHigh | over 5% of checkout requests fail for 1 min | page |
| CheckoutLatencyHigh | checkout p95 over 1.5 s for 1 min | page |
| CartErrorRateHigh | over 5% of cart requests fail for 1 min | page |
| CartLatencyHigh | cart p95 over 500 ms for 1 min | page |
| ShippingErrorRateHigh | over 5% of shipping requests fail for 1 min | page |
| CatalogErrorRateHigh | over 2% of catalog requests fail for 2 min | ticket |
| RecommendationLatencyHigh | recommendation p95 over 500 ms for 2 min | ticket |
| OrdersBacklogHigh | the fulfillment consumer group is over 20 orders behind for 2 min | ticket |
| OrdersDeadLettered | any message written to `orders.dlq` in the last 10 min | ticket |
| StorefrontTrafficSurge | storefront traffic over 3× its recent average for 2 min | ticket |
| ContainerRestarting | a container restarts twice within 10 min | ticket |

Error-ratio alerts also require a minimum request rate. The rules have unit tests in [`alerts/tests/`](alerts/tests/). No notification channel is configured; add a receiver in `observability/stack-a/alertmanager.yml`.

## Running it

Requires Docker with Compose v2, about 2 GB of free memory, and [uv](https://docs.astral.sh/uv/) for local development.

```bash
make up              # build images and start everything
make smoke           # after a few minutes: check telemetry and alerts, print resource usage
make down            # stop (make clean also deletes data)
```

| UI | URL |
| --- | --- |
| Shop | http://localhost:8080 |
| Grafana | http://localhost:3000 |
| Prometheus | http://localhost:9090 |
| Alertmanager | http://localhost:9093 |

Development: `uv sync`, then `make check` (ruff, pyright, pytest) and `make check-config` (compose, collector, Prometheus and Alertmanager config, alert rule tests).

Service versions and settings are in [`.env`](.env).

## Footprint

Measured with `make smoke` after 5 minutes of traffic from 20 simulated shoppers on a 4-CPU, 16 GB Linux machine: 18 containers, **about 1.6 GiB of memory** in total and under one CPU core. The eight Python services use 40–65 MiB each; the largest containers are Kafka (364 MiB), Grafana (258 MiB) and Tempo (220 MiB).

The `stack` workflow repeats the measurement on a GitHub-hosted runner for every pull request and writes it to the run summary.

## License

[MIT](LICENSE)
