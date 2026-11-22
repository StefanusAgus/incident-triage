"""Generate a repeatable synthetic dataset using only the standard library."""

import argparse
import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEED = 42
DEFAULT_NUM_SAMPLE = 300
START_DATE = datetime(2026, 1, 1, tzinfo=timezone.utc)
END_DATE = datetime(2026, 7, 1, tzinfo=timezone.utc)
ENVIRONMENTS = ("dev", "qa", "stage", "prod")
OUTPUT_PATH = Path(__file__).resolve().with_name("incidents.json")


@dataclass(frozen=True)
class IncidentFamily:
    services: tuple[str, ...]
    severities: tuple[str, ...]
    titles: tuple[str, ...]
    symptoms: tuple[str, ...]
    cause: str
    resolution: str
    tags: tuple[str, ...]


# Each family keeps a single root cause and matching resolution. Only wording,
# compatible services, environment, severity, and occurrence time vary.
FAMILIES = (
    IncidentFamily(
        services=("orders-api", "catalog-api", "inventory-api"),
        severities=("SEV1", "SEV2", "SEV3"),
        titles=("{service} returns 503 when database connections run out",
                "Database connection exhaustion causes {service} failures"),
        symptoms=("Requests failed with connection acquisition timeouts during a traffic spike.",
                  "HTTP 503 responses increased as the database connection pool reached its limit."),
        cause="Connections were not released after exceptions in request handlers.",
        resolution="Fixed connection cleanup in the exception handler, restarted affected instances, and verified pool usage recovered.",
        tags=("database", "connection-pool", "http-503"),
    ),
    IncidentFamily(
        services=("orders-api", "billing-api", "inventory-api"),
        severities=("SEV2", "SEV3", "SEV4"),
        titles=("{service} returns 503 after configuration deployment",
                "Incorrect database hostname breaks {service} readiness"),
        symptoms=("All newly deployed instances failed readiness checks.",
                  "The rollout stalled with HTTP 503 responses and database host lookup failures."),
        cause="The database hostname in the new configuration was incorrect.",
        resolution="Restored the correct database hostname and redeployed. Readiness checks and database connectivity passed.",
        tags=("configuration", "deployment", "http-503"),
    ),
    IncidentFamily(
        services=("auth-service", "payments-api", "orders-api"),
        severities=("SEV1", "SEV2", "SEV3"),
        titles=("Service authentication fails after certificate expiry in {service}",
                "Expired client certificate blocks {service} requests"),
        symptoms=("Service-to-service requests failed with certificate-expired errors.",
                  "Mutual TLS handshakes failed and downstream authentication was rejected."),
        cause="The client certificate had not been renewed before expiry.",
        resolution="Renewed the client certificate, reloaded the service, and verified successful TLS authentication.",
        tags=("authentication", "certificate", "tls"),
    ),
    IncidentFamily(
        services=("notifications-worker", "orders-worker", "billing-worker"),
        severities=("SEV2", "SEV3", "SEV4"),
        titles=("Queue backlog grows while {service} workers are saturated",
                "Insufficient {service} consumers delay queued jobs"),
        symptoms=("Queue depth and oldest message age increased under sustained load.",
                  "Queued jobs were delayed while worker CPU usage stayed near capacity."),
        cause="The consumer replica count was too low for the incoming message rate.",
        resolution="Increased consumer replicas within downstream capacity, drained the queue, and configured scaling on queue age.",
        tags=("queue", "backlog", "worker-capacity"),
    ),
    IncidentFamily(
        services=("orders-api", "payments-api", "notifications-worker"),
        severities=("SEV2", "SEV3", "SEV4"),
        titles=("DNS lookup timeouts interrupt {service} outbound requests",
                "Stale resolver configuration causes DNS errors in {service}"),
        symptoms=("Outbound calls failed intermittently with temporary name resolution errors.",
                  "DNS queries timed out even though target services were healthy."),
        cause="The resolver configuration still referenced a DNS server removed during maintenance.",
        resolution="Removed the retired DNS server from resolver configuration, reloaded affected instances, and verified repeated name lookups.",
        tags=("dns", "network", "timeout"),
    ),
    IncidentFamily(
        services=("payments-api", "checkout-api", "billing-api"),
        severities=("SEV1", "SEV2", "SEV3"),
        titles=("Payment provider connections time out in {service}",
                "Egress firewall blocks {service} payment requests"),
        symptoms=("Payment authorization attempts timed out before a connection was established.",
                  "Payment requests failed with TCP connect timeouts after a network policy change."),
        cause="An egress firewall rule blocked the payment provider's documented address range.",
        resolution="Restored the payment provider egress allowlist and verified connectivity. Reconciled payment statuses before retrying unresolved authorizations.",
        tags=("payment", "timeout", "firewall"),
    ),
    IncidentFamily(
        services=("reports-worker", "billing-worker", "audit-service"),
        severities=("SEV1", "SEV2", "SEV3"),
        titles=("{service} stops writing when storage capacity is exhausted",
                "Unrotated logs fill the {service} data volume"),
        symptoms=("Jobs failed with no-space-left-on-device errors.",
                  "Disk utilization reached capacity and writes to the local volume failed."),
        cause="Log rotation was disabled, allowing local application logs to fill the volume.",
        resolution="Archived and removed expired application logs, restored log rotation, and verified free space and successful writes.",
        tags=("storage", "disk-full", "log-rotation"),
    ),
    IncidentFamily(
        services=("catalog-api", "inventory-api", "pricing-api"),
        severities=("SEV2", "SEV3", "SEV4"),
        titles=("Synchronized cache expiry increases {service} latency",
                "Cache stampede overloads {service} database reads"),
        symptoms=("Latency and database reads spiked when popular cache entries expired together.",
                  "A sudden drop in cache hit rate coincided with slow responses and database load."),
        cause="Popular cache entries used identical expiration times, triggering concurrent refreshes.",
        resolution="Added expiration jitter and single-flight cache refresh, warmed popular entries, and verified database load stabilized.",
        tags=("cache", "latency", "database"),
    ),
    IncidentFamily(
        services=("notifications-worker", "webhooks-worker", "sync-worker"),
        severities=("SEV2", "SEV3", "SEV4"),
        titles=("Immediate retries amplify provider rate limits in {service}",
                "{service} retry storm triggers repeated HTTP 429 responses"),
        symptoms=("The external provider returned HTTP 429 while retry volume continued rising.",
                  "Delivery delays increased as rejected requests were immediately resubmitted."),
        cause="The retry loop ignored Retry-After and had no backoff or concurrency cap.",
        resolution="Honored Retry-After, added exponential backoff with jitter, capped concurrency, and verified delivery recovered within provider limits.",
        tags=("rate-limit", "retry", "http-429"),
    ),
    IncidentFamily(
        services=("reports-worker", "exports-worker", "analytics-worker"),
        severities=("SEV2", "SEV3", "SEV4"),
        titles=("Large export exhausts memory in {service}",
                "Unbounded export buffering causes {service} restarts"),
        symptoms=("Large export jobs were killed when memory usage exceeded the container limit.",
                  "Worker restarts interrupted exports while smaller jobs continued to succeed."),
        cause="The export implementation buffered the entire result set in memory.",
        resolution="Replaced full-result buffering with bounded streaming batches, reran failed exports, and verified memory stayed within limits.",
        tags=("memory", "export", "oom"),
    ),
    IncidentFamily(
        services=("orders-api", "billing-api", "catalog-api"),
        severities=("SEV1", "SEV2", "SEV3"),
        titles=("Missing schema migration causes {service} errors after release",
                "{service} queries fail because a required column is absent"),
        symptoms=("Requests returned HTTP 500 with column-does-not-exist errors after deployment.",
                  "The new application release failed queries referencing a newly introduced column."),
        cause="The application was deployed before its backward-compatible database migration ran.",
        resolution="Rolled back the application, applied and verified the missing migration, then redeployed and checked affected queries.",
        tags=("database", "migration", "http-500"),
    ),
    IncidentFamily(
        services=("inventory-api", "catalog-api", "orders-api"),
        severities=("SEV2", "SEV3", "SEV4"),
        titles=("Missing database index slows {service} lookups",
                "Full table scans increase {service} request latency"),
        symptoms=("Filtered lookup requests became slow as the table grew.",
                  "Request latency rose alongside database CPU and rows scanned per query."),
        cause="A frequently used filter column had no supporting index, causing full table scans.",
        resolution="Added an index matching the lookup filter, verified the query plan used it, and confirmed latency and database CPU recovered.",
        tags=("database", "index", "latency"),
    ),
)


def generate_incidents(num_sample: int = DEFAULT_NUM_SAMPLE) -> list[dict[str, object]]:
    """Return the requested number of incidents, cycling through the families."""
    if num_sample < 0:
        raise ValueError("num_sample must be non-negative")
    rng = random.Random(SEED)
    date_range_seconds = int((END_DATE - START_DATE).total_seconds())
    incidents = []
    for index in range(num_sample):
        family = FAMILIES[index % len(FAMILIES)]
        service = rng.choice(family.services)
        created_at = START_DATE + timedelta(seconds=rng.randrange(date_range_seconds))
        incidents.append({
            "id": f"INC-{index + 1:04d}",
            "created_at": created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "environment": rng.choice(ENVIRONMENTS),
            "service": service,
            "severity": rng.choice(family.severities),
            "title": rng.choice(family.titles).format(service=service),
            "description": f"{rng.choice(family.symptoms)} {family.cause}",
            "resolution_summary": family.resolution,
            "tags": list(family.tags),
        })
    return incidents


def main(num_sample: int = DEFAULT_NUM_SAMPLE) -> None:
    incidents = generate_incidents(num_sample)
    OUTPUT_PATH.write_text(
        json.dumps(incidents, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"Generated {len(incidents)} incidents in {OUTPUT_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--num-sample", type=int, default=DEFAULT_NUM_SAMPLE,
        help="Number of incidents to generate (default: %(default)s)",
    )
    args = parser.parse_args()
    if args.num_sample < 0:
        parser.error("--num-sample must be non-negative")
    main(num_sample=args.num_sample)
