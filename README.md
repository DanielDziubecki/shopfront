# Shopfront

[![stack](https://github.com/DanielDziubecki/shopfront/actions/workflows/stack.yml/badge.svg)](https://github.com/DanielDziubecki/shopfront/actions/workflows/stack.yml)

An online store built from microservices in eight languages, fully instrumented with OpenTelemetry and shipped with an open-source observability stack and service-level alerts. Derived from the [OpenTelemetry Demo](https://github.com/open-telemetry/opentelemetry-demo) 3.1.0 (see [NOTICE](NOTICE)).

## Services

| Service | Language | Role | Talks to |
| --- | --- | --- | --- |
| frontend-proxy | Envoy | Entry point on port 8080 | frontend, image-provider |
| frontend | TypeScript (Next.js) | Web UI and API | ad, cart, checkout, currency, product-catalog, recommendation, shipping |
| checkout | Go | Places orders | cart, currency, email, payment, product-catalog, shipping, Kafka `orders` |
| cart | C# | Shopping carts | valkey-cart |
| product-catalog | Go | Product data | astronomy-db (PostgreSQL) |
| recommendation | Python | Product recommendations | product-catalog |
| payment | JavaScript | Charges cards | |
| shipping | Rust | Shipping quotes | quote |
| quote | PHP | Shipping cost calculation | |
| currency | C++ | Currency conversion | |
| email | Ruby | Order confirmations | |
| ad | Java | Contextual ads | |
| accounting | C# | Consumes orders from Kafka | Kafka `orders`, astronomy-db |
| image-provider | nginx | Product images | |
| load-generator | Python (Locust) | Simulated shoppers (20 by default) | frontend-proxy |

Data stores and messaging: PostgreSQL (`astronomy-db`), Valkey (`valkey-cart`), Kafka.

## Observability (stack A)

All services send traces, metrics and logs over OTLP to the OpenTelemetry Collector, which forwards them to:

| Signal | Backend | Notes |
| --- | --- | --- |
| Traces | Tempo | The metrics generator adds service-graph metrics |
| Metrics | Prometheus | OTLP receiver; request rate, errors and latency per service come from the collector's span metrics connector; container CPU, memory and restarts from Docker; Kafka, PostgreSQL and Valkey metrics from collector receivers |
| Logs | Loki | `service_name` label, trace and span ids attached |
| Alerts | Prometheus rules → Alertmanager | Shown in Grafana under Alerting |
| Dashboards | Grafana | Data sources for all of the above, linked trace ↔ logs ↔ metrics |

Configuration lives in [`observability/stack-a/`](observability/stack-a/); alert rules in [`alerts/`](alerts/).

## Alerts

Service-level, symptom-based alerts on request error ratio, latency, consumer lag, traffic and restarts:

| Alert | Fires when | Severity |
| --- | --- | --- |
| FrontendErrorRateHigh | over 5% of frontend requests fail for 1 min | page |
| FrontendLatencyHigh | frontend p95 over 1 s for 2 min | page |
| CheckoutErrorRateHigh | over 5% of checkout requests fail for 1 min | page |
| CheckoutLatencyHigh | checkout p95 over 2 s for 1 min | page |
| CartErrorRateHigh | over 5% of cart requests fail for 1 min | page |
| CartLatencyHigh | cart p95 over 1 s for 1 min | page |
| ShippingErrorRateHigh | over 5% of shipping requests fail for 1 min | page |
| ProductCatalogErrorRateHigh | over 2% of product catalog requests fail for 2 min | ticket |
| RecommendationLatencyHigh | recommendation p95 over 500 ms for 2 min | ticket |
| OrdersConsumerLagHigh | a consumer group is over 10 messages behind on `orders` for 2 min | ticket |
| FrontendTrafficSurge | frontend traffic over 3× its recent average for 2 min | ticket |
| ContainerRestarting | a container restarts twice within 10 min | ticket |

Error-ratio alerts also require a minimum request rate, so a handful of requests can't page. The rules have unit tests in [`alerts/tests/`](alerts/tests/). No notification channel is configured; add a receiver in `observability/stack-a/alertmanager.yml`.

## Running it

Requires Docker with Compose v2, about 3 GB of free memory and 10 GB of disk for images (see [Footprint](#footprint)).

```bash
make up              # pull images and start everything
make smoke           # wait for traffic, check telemetry and alerts, print resource usage
make down            # stop (make clean also deletes stored telemetry)
```

| UI | URL |
| --- | --- |
| Store | http://localhost:8080 |
| Grafana | http://localhost:3000 |
| Prometheus | http://localhost:9090 |
| Alertmanager | http://localhost:9093 |

Other targets: `make ps`, `make logs SERVICE=checkout`, `make check-config` (validates compose, collector, Prometheus and Alertmanager configuration and runs the alert rule tests).

Images are the published upstream 3.1.0 images from Docker Hub (`otel/demo`); every service's source is in [`src/`](src/) and builds with `docker compose build <service>`.

## Footprint

Measured with `make smoke` after 5 minutes of traffic from 20 simulated users on a 4-CPU, 16 GB Linux machine: 25 containers, **about 2.0 GiB of memory** in total and about half a CPU core.

| Largest containers | Peak memory |
| --- | ---: |
| kafka | 509 MiB |
| tempo | 213 MiB |
| ad | 206 MiB |
| grafana | 199 MiB |
| accounting | 117 MiB |
| everything else (20 containers) | about 800 MiB |

The `stack` workflow repeats the measurement on a GitHub-hosted runner for every pull request and writes it to the run summary.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
