STACK ?= a
COMPOSE = docker compose -f compose.yaml -f observability/stack-$(STACK)/compose.yaml
PROMETHEUS_IMAGE = $(shell grep '^PROMETHEUS_IMAGE=' .env | cut -d= -f2)
ALERTMANAGER_IMAGE = $(shell grep '^ALERTMANAGER_IMAGE=' .env | cut -d= -f2)

.PHONY: up down clean ps logs pull smoke check-config

up:            ## Start the application with observability stack $(STACK)
	$(COMPOSE) up -d --no-build

down:          ## Stop everything, keep data volumes
	$(COMPOSE) down

clean:         ## Stop everything and delete data volumes
	$(COMPOSE) down -v

ps:
	$(COMPOSE) ps

logs:          ## Follow logs, e.g. make logs SERVICE=checkout
	$(COMPOSE) logs -f $(SERVICE)

pull:
	$(COMPOSE) pull

smoke:         ## Check a running stack and measure its footprint
	python3 scripts/smoke.py

check-config:  ## Validate compose, collector, Prometheus and Alertmanager config; unit-test alert rules
	$(COMPOSE) config --quiet
	$(COMPOSE) run --rm --no-deps --entrypoint /otelcol-contrib otel-collector validate --config=/etc/otelcol/config.yml
	docker run --rm -v $(CURDIR)/observability/stack-a/prometheus.yml:/etc/prometheus/prometheus.yml:ro -v $(CURDIR)/alerts:/etc/prometheus/rules:ro --entrypoint promtool $(PROMETHEUS_IMAGE) check config /etc/prometheus/prometheus.yml
	docker run --rm -v $(CURDIR):/w:ro -w /w/alerts/tests --entrypoint promtool $(PROMETHEUS_IMAGE) test rules slo.test.yml
	docker run --rm -v $(CURDIR):/w:ro --entrypoint amtool $(ALERTMANAGER_IMAGE) check-config /w/observability/stack-a/alertmanager.yml
