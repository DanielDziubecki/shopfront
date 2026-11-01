#!/usr/bin/env python3
"""Smoke-test a running stack and measure its footprint.

Checks that every container is up, that traces, logs and request metrics arrive for every
service, that the alert rules load (in Prometheus and in Grafana) and that no alert fires on
a healthy system. Then samples per-container CPU and memory.

Writes a Markdown report to stdout (and to $GITHUB_STEP_SUMMARY when set) and a JSON report
to --json. Exits non-zero if any check fails.

Usage: scripts/smoke.py [--warmup SECONDS] [--json PATH]
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from typing import Any

PROMETHEUS = "http://127.0.0.1:9090"
LOKI = "http://127.0.0.1:3100"
TEMPO = "http://127.0.0.1:3200"
GRAFANA = "http://127.0.0.1:3000"

APP_SERVICES = {
    "accounting", "ad", "cart", "checkout", "currency", "email", "frontend", "frontend-proxy",
    "load-generator", "payment", "product-catalog", "quote", "recommendation", "shipping",
}  # fmt: skip
TRACED = APP_SERVICES | {"image-provider"}
LOGGING = APP_SERVICES


def get_json(url: str, params: dict[str, str] | None = None) -> Any:
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.load(resp)


def prom_query(expr: str) -> list[dict[str, Any]]:
    return get_json(f"{PROMETHEUS}/api/v1/query", {"query": expr})["data"]["result"]


def containers() -> list[dict[str, Any]]:
    out = subprocess.run(
        ["docker", "ps", "--all", "--format", "json"], check=True, capture_output=True, text=True
    ).stdout
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def wait_for_containers(timeout_s: int) -> list[str]:
    """Wait until every container is running and none is starting or unhealthy."""
    deadline = time.monotonic() + timeout_s
    problems: list[str] = []
    while time.monotonic() < deadline:
        problems = [
            f"{c['Names']}: {c['Status']}"
            for c in containers()
            if c["State"] != "running" or "starting" in c["Status"] or "unhealthy" in c["Status"]
        ]
        if not problems:
            return []
        time.sleep(5)
    return problems


def check_services(name: str, seen: set[str], expected: set[str]) -> tuple[str, bool, str]:
    missing = sorted(expected - seen)
    detail = f"missing: {', '.join(missing)}" if missing else f"{len(expected)} services"
    return name, not missing, detail


def run_checks() -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []

    metric_services = {
        r["metric"].get("service_name", "")
        for r in prom_query("count by (service_name) (traces_span_metrics_calls_total)")
    }
    checks.append(check_services("request metrics (Prometheus)", metric_services, TRACED))

    tempo = get_json(f"{TEMPO}/api/v2/search/tag/resource.service.name/values")
    checks.append(
        check_services("traces (Tempo)", {v["value"] for v in tempo["tagValues"]}, TRACED)
    )

    loki = get_json(f"{LOKI}/loki/api/v1/label/service_name/values")
    checks.append(check_services("logs (Loki)", set(loki.get("data", [])), LOGGING))

    groups = get_json(f"{PROMETHEUS}/api/v1/rules")["data"]["groups"]
    rules = [r for g in groups for r in g["rules"]]
    unhealthy = [r["name"] for r in rules if r["health"] == "err"]
    alerting = [r for r in rules if r["type"] == "alerting"]
    checks.append(
        (
            "alert rules loaded (Prometheus)",
            bool(alerting) and not unhealthy,
            f"{len(alerting)} alerts, {len(rules) - len(alerting)} recording rules"
            + (f"; errors: {', '.join(unhealthy)}" if unhealthy else ""),
        )
    )

    grafana = get_json(f"{GRAFANA}/api/prometheus/prometheus/api/v1/rules")
    grafana_alerts = sum(
        1 for g in grafana["data"]["groups"] for r in g["rules"] if r["type"] == "alerting"
    )
    checks.append(
        (
            "alert rules visible (Grafana)",
            grafana_alerts == len(alerting),
            f"{grafana_alerts} alerts",
        )
    )

    firing = [
        f"{a['labels']['alertname']}({a['labels'].get('service_name') or a['labels'].get('container_name', '')})"
        for a in get_json(f"{PROMETHEUS}/api/v1/alerts")["data"]["alerts"]
        if a["state"] == "firing"
    ]
    checks.append(
        ("no alerts firing on a healthy system", not firing, ", ".join(firing) or "none firing")
    )
    return checks


def parse_mib(text: str) -> float:
    value = text.strip()
    units = {"KiB": 1 / 1024, "MiB": 1.0, "GiB": 1024.0, "kB": 1 / 1024, "MB": 1.0, "GB": 1024.0}
    for unit, factor in units.items():
        if value.endswith(unit):
            return float(value[: -len(unit)]) * factor
    return float(value.rstrip("B")) / (1024 * 1024)


def sample_resources(samples: int, interval_s: int) -> dict[str, dict[str, float]]:
    """Per-container peak memory (MiB) and mean CPU (%) over several `docker stats` samples."""
    per: dict[str, dict[str, list[float]]] = {}
    for i in range(samples):
        out = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "json"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        for line in out.splitlines():
            stat = json.loads(line)
            entry = per.setdefault(stat["Name"], {"mem": [], "cpu": []})
            entry["mem"].append(parse_mib(stat["MemUsage"].split("/")[0]))
            entry["cpu"].append(float(stat["CPUPerc"].rstrip("%")))
        if i < samples - 1:
            time.sleep(interval_s)
    return {
        name: {"mem_mib": max(v["mem"]), "cpu_pct": sum(v["cpu"]) / len(v["cpu"])}
        for name, v in per.items()
    }


def host_info() -> dict[str, float]:
    meminfo: dict[str, int] = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, value = line.split(":", 1)
            meminfo[key] = int(value.split()[0])
    return {
        "cpus": os.cpu_count() or 0,
        "mem_total_mib": meminfo["MemTotal"] / 1024,
        "mem_available_mib": meminfo["MemAvailable"] / 1024,
    }


def report(
    checks: list[tuple[str, bool, str]],
    resources: dict[str, dict[str, float]],
    host: dict[str, float],
) -> str:
    lines = ["## Stack smoke test", "", "| Check | Result | Detail |", "| --- | --- | --- |"]
    lines += [f"| {name} | {'pass' if ok else 'FAIL'} | {detail} |" for name, ok, detail in checks]
    total_mem = sum(r["mem_mib"] for r in resources.values())
    total_cpu = sum(r["cpu_pct"] for r in resources.values())
    lines += [
        "",
        "## Resources",
        "",
        f"Host: {host['cpus']:.0f} CPUs, {host['mem_total_mib'] / 1024:.1f} GiB memory, "
        f"{host['mem_available_mib'] / 1024:.1f} GiB available while the stack runs.",
        f"Containers: {len(resources)}, peak memory {total_mem / 1024:.2f} GiB in total, "
        f"mean CPU {total_cpu:.0f}% (100% = one core).",
        "",
        "| Container | Peak memory (MiB) | Mean CPU (%) |",
        "| --- | ---: | ---: |",
    ]
    for name, r in sorted(resources.items(), key=lambda kv: -kv[1]["mem_mib"]):
        lines.append(f"| {name} | {r['mem_mib']:.0f} | {r['cpu_pct']:.1f} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--startup-timeout", type=int, default=600)
    parser.add_argument("--warmup", type=int, default=300, help="seconds of traffic before checks")
    parser.add_argument("--samples", type=int, default=6)
    parser.add_argument("--json", default="smoke-report.json")
    args = parser.parse_args()

    problems = wait_for_containers(args.startup_timeout)
    if problems:
        print("Containers not ready:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    print(f"All containers up; warming up for {args.warmup}s", file=sys.stderr)
    time.sleep(args.warmup)

    checks = run_checks()
    resources = sample_resources(args.samples, interval_s=10)
    host = host_info()

    text = report(checks, resources, host)
    print(text)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a") as f:
            f.write(text)
    with open(args.json, "w") as f:
        json.dump(
            {
                "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks],
                "resources": resources,
                "host": host,
            },
            f,
            indent=2,
        )
    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
