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
class Scenario:
    """Symptoms, cause, and fix travel together, never sampled independently."""

    title: str
    symptom: str
    cause: str
    resolution: str
    tag: str


@dataclass(frozen=True)
class Context:
    label: str
    description: str
    verification: str


@dataclass(frozen=True)
class IncidentFamily:
    services: tuple[str, ...]
    severities: tuple[str, ...]
    tags: tuple[str, ...]
    scenarios: tuple[Scenario, ...]
    contexts: tuple[Context, ...]


ROLLOUT_CONTEXTS = (
    Context("rolling replacement", "The issue affected {service} during a rolling deployment.",
            "Verified mixed-version traffic and readiness checks for {service}."),
    Context("new replica startup", "The issue was detected while {service} replicas were being replaced.",
            "Verified cold-start readiness and request handling on {service} replicas."),
    Context("autoscaling", "The issue appeared as {service} scaled out to handle additional traffic.",
            "Verified newly scaled {service} replicas handled canary requests."),
    Context("recovery rehearsal", "A recovery rehearsal exercised {service} alongside the current deployment.",
            "Repeated the {service} recovery rehearsal and checked representative requests."),
    Context("blue-green cutover", "Failures were detected during blue-green cutover checks for {service}.",
            "Verified {service} readiness and canary traffic before completing the cutover."),
)

FAMILIES = (
    IncidentFamily(
        services=("orders-api", "catalog-api", "inventory-api"),
        severities=("SEV1", "SEV2", "SEV3"),
        tags=("database", "connection-pool", "http-503"),
        scenarios=(
            Scenario(
                "HTTP 503 from leaked database connections",
                "Connection acquisition timed out during a traffic spike.",
                "Exception paths left pooled database connections open.",
                "Fixed exception-path connection cleanup and recycled affected instances.",
                "connection-leak",
            ),
            Scenario(
                "HTTP 503 from an undersized database connection pool",
                "Requests exceeded the pool wait timeout as concurrent traffic increased.",
                "A reduced pool limit could not support measured concurrency, although connections were released correctly.",
                "Restored the tested pool limit within the database connection budget and verified peak-load recovery.",
                "pool-sizing",
            ),
            Scenario(
                "Database connection exhaustion behind long transactions",
                "HTTP 503 responses rose while connections stayed busy on blocked transactions.",
                "An import transaction held row locks while making slow external calls.",
                "Moved external calls outside the transaction, shortened transaction scope, and verified lock waits cleared.",
                "long-transactions",
            ),
        ),
        contexts=(
            Context("list reads", "Failures affected GET /{resource} list requests.",
                    "Verified paginated GET /{resource} reads through {service}."),
            Context("detail reads", "Failures affected GET /{resource}/{{id}} detail requests.",
                    "Verified representative GET /{resource}/{{id}} requests through {service}."),
            Context("batch lookups", "Partner batch lookups failed on POST /{resource}/batch.",
                    "Replayed partner batches against POST /{resource}/batch through {service}."),
            Context("change synchronization", "Scheduled clients failed while reading /{resource}/changes.",
                    "Verified scheduled /{resource}/changes synchronization through {service}."),
            Context("summary aggregation", "Dashboard aggregation failed on GET /{resource}/summary.",
                    "Verified summary requests and connection usage through {service}."),
        ),
    ),
    IncidentFamily(
        services=("orders-api", "billing-api", "inventory-api"),
        severities=("SEV2", "SEV3", "SEV4"),
        tags=("configuration", "deployment", "http-503"),
        scenarios=(
            Scenario(
                "HTTP 503 after database hostname configuration deployment",
                "Instances failed readiness checks with database host lookup errors.",
                "The deployed database hostname contained a typo.",
                "Restored the correct database hostname and redeployed the configuration.",
                "bad-hostname",
            ),
            Scenario(
                "HTTP 503 after a deployment omitted the database secret",
                "Readiness probes failed with database authentication errors.",
                "The deployment referenced a secret key absent from the target environment.",
                "Corrected the secret reference, restored the required credential, and redeployed.",
                "missing-secret",
            ),
            Scenario(
                "HTTP 503 after malformed database port configuration",
                "Instances could not initialize the database client after configuration deployment.",
                "A configuration override supplied a non-numeric database port.",
                "Restored the numeric port, added deployment-time configuration validation, and redeployed.",
                "bad-port",
            ),
        ),
        contexts=ROLLOUT_CONTEXTS,
    ),
    IncidentFamily(
        services=("auth-service", "payments-api", "orders-api"),
        severities=("SEV1", "SEV2", "SEV3"),
        tags=("authentication", "certificate", "tls"),
        scenarios=(
            Scenario(
                "Service authentication fails after client certificate expiry",
                "Mutual TLS handshakes returned certificate-expired errors.",
                "The client certificate was not renewed before its expiry date.",
                "Renewed the client certificate, reloaded the service, and verified successful authentication.",
                "expired-client-certificate",
            ),
            Scenario(
                "TLS authentication fails with an incomplete certificate chain",
                "Peers rejected the client certificate with unable-to-get-issuer errors.",
                "The deployed certificate bundle omitted its intermediate certificate.",
                "Installed the complete certificate chain and reloaded the TLS client.",
                "certificate-chain",
            ),
            Scenario(
                "Certificate authentication fails after trust-root rotation",
                "TLS requests returned unknown-authority errors after the issuer changed.",
                "Instances retained a trust bundle without the replacement certificate authority.",
                "Installed the updated trust bundle, reloaded instances, and verified the new issuer chain.",
                "stale-trust-bundle",
            ),
        ),
        contexts=(
            Context("internal probes", "Internal probes could not authenticate to {service} dependencies.",
                    "Repeated internal TLS probes from {service}."),
            Context("dependency calls", "Dependency calls originating from {service} were rejected.",
                    "Verified authenticated dependency calls from {service}."),
            Context("scheduled credential refresh", "Scheduled credential refresh requests from {service} failed at TLS negotiation.",
                    "Verified the next scheduled credential refresh from {service}."),
            Context("callback acknowledgements", "Callback acknowledgement requests from {service} failed before HTTP exchange.",
                    "Verified authenticated callback acknowledgements from {service}."),
            Context("background reconciliation", "Background reconciliation in {service} could not establish authenticated connections.",
                    "Completed a background reconciliation cycle in {service}."),
        ),
    ),
    IncidentFamily(
        services=("notifications-worker", "orders-worker", "billing-worker"),
        severities=("SEV2", "SEV3", "SEV4"),
        tags=("queue", "backlog"),
        scenarios=(
            Scenario(
                "Queue backlog grows with insufficient consumers",
                "Queue depth and oldest message age increased while worker CPU stayed saturated.",
                "The consumer replica count was too low for the incoming message rate.",
                "Increased consumer replicas within downstream capacity and enabled scaling on oldest message age.",
                "consumer-capacity",
            ),
            Scenario(
                "Queue backlog stalls behind a poison message",
                "The same message repeatedly failed and prevented ordered deliveries from advancing.",
                "A malformed payload retried indefinitely without a dead-letter policy.",
                "Quarantined the malformed message and configured bounded retries with a dead-letter destination.",
                "poison-message",
            ),
            Scenario(
                "Queue backlog follows downstream throttling",
                "Consumers spent most of their time retrying downstream HTTP 429 responses.",
                "Consumer concurrency exceeded the downstream request quota.",
                "Capped consumer concurrency, honored Retry-After, and drained the queue at the supported rate.",
                "consumer-throttling",
            ),
        ),
        contexts=(
            Context("priority deliveries", "Delayed jobs accumulated on {resource}.priority.",
                    "Verified message age and completion on {resource}.priority through {service}."),
            Context("bulk processing", "Delayed jobs accumulated on {resource}.bulk.",
                    "Verified bulk message completion and queue age through {service}."),
            Context("retry recovery", "Recovery jobs stopped advancing on {resource}.retry.",
                    "Verified retry deliveries completed through {service}."),
            Context("regional processing", "Regional jobs accumulated on {resource}.regional.",
                    "Verified regional partition progress through {service}."),
            Context("scheduled processing", "Scheduled jobs were delayed on {resource}.scheduled.",
                    "Verified the next scheduled message batch through {service}."),
        ),
    ),
    IncidentFamily(
        services=("orders-api", "payments-api", "notifications-worker"),
        severities=("SEV2", "SEV3", "SEV4"),
        tags=("dns", "network"),
        scenarios=(
            Scenario(
                "DNS lookup timeouts after resolver maintenance",
                "Outbound calls failed intermittently with temporary name resolution errors.",
                "Resolver configuration still referenced a DNS server retired during maintenance.",
                "Removed the retired resolver, reloaded the configuration, and verified repeated DNS lookups.",
                "stale-resolver",
            ),
            Scenario(
                "DNS lookups fail with cached NXDOMAIN responses",
                "A newly created hostname kept returning NXDOMAIN on affected instances.",
                "A local DNS cache retained the negative response from before the record existed.",
                "Flushed the negative cache and bounded negative caching by the authoritative TTL.",
                "negative-dns-cache",
            ),
            Scenario(
                "DNS errors follow an incorrect search suffix",
                "Short hostnames failed resolution while fully qualified names worked.",
                "A deployment changed the DNS search suffix to the wrong internal zone.",
                "Restored the internal search suffix and configured fully qualified dependency names.",
                "dns-search-suffix",
            ),
        ),
        contexts=(
            Context("database discovery", "{service} could not resolve the database dependency for {resource}.",
                    "Verified database dependency name resolution from {service}."),
            Context("provider discovery", "{service} could not resolve its configured provider host.",
                    "Verified provider DNS resolution and connection establishment from {service}."),
            Context("broker discovery", "{service} could not resolve its configured broker host.",
                    "Verified broker DNS resolution and connectivity from {service}."),
            Context("telemetry delivery", "{service} could not resolve the telemetry collector host.",
                    "Verified collector DNS resolution and telemetry delivery from {service}."),
            Context("callback discovery", "{service} could not resolve its configured callback host.",
                    "Verified callback host resolution and delivery from {service}."),
        ),
    ),
    IncidentFamily(
        services=("payments-api", "checkout-api", "billing-api"),
        severities=("SEV1", "SEV2", "SEV3"),
        tags=("payment", "timeout"),
        scenarios=(
            Scenario(
                "Payment requests time out behind an egress firewall",
                "Provider calls hit TCP connect timeouts before establishing a connection.",
                "An egress rule blocked the payment provider's documented address range.",
                "Restored the provider egress allowlist and verified connectivity; reconciled payment statuses before retrying unresolved operations.",
                "egress-firewall",
            ),
            Scenario(
                "Payment provider latency exceeds the read timeout",
                "Connections succeeded but provider responses exceeded the read deadline.",
                "The provider was processing requests more slowly during a reported degradation.",
                "Enabled the payment circuit breaker, confirmed provider recovery, and reconciled statuses before retrying with idempotency keys.",
                "provider-latency",
            ),
            Scenario(
                "Payment requests time out waiting for an HTTP client connection",
                "Requests expired in the client connection pool before reaching the provider.",
                "Unclosed HTTP response bodies exhausted the outbound client pool.",
                "Closed response bodies on every code path, recycled the client pool, and reconciled outstanding payment statuses.",
                "http-client-pool",
            ),
        ),
        contexts=(
            Context("authorization", "Payment authorization requests through {service} were affected.",
                    "Verified authorization and status reconciliation through {service}."),
            Context("capture", "Previously authorized payment captures through {service} were affected.",
                    "Verified capture processing and duplicate-charge protection through {service}."),
            Context("refunds", "Refund requests through {service} were affected.",
                    "Verified refund processing and reconciliation through {service}."),
            Context("recurring charges", "Recurring charge requests through {service} were affected.",
                    "Verified recurring billing and idempotent retries through {service}."),
            Context("status reconciliation", "Payment status reconciliation through {service} was affected.",
                    "Verified payment status reads and reconciliation completion through {service}."),
        ),
    ),
    IncidentFamily(
        services=("reports-worker", "billing-worker", "audit-service"),
        severities=("SEV1", "SEV2", "SEV3"),
        tags=("storage", "disk-full"),
        scenarios=(
            Scenario(
                "Storage full after application logs stop rotating",
                "Writes failed with no-space-left-on-device errors on the application volume.",
                "Disabled log rotation allowed local application logs to consume available storage.",
                "Archived expired logs, restored rotation and retention limits, and verified free space recovered.",
                "log-rotation",
            ),
            Scenario(
                "Storage full after abandoned temporary files accumulate",
                "New jobs could not create scratch files because the work volume was full.",
                "Failed jobs left temporary files behind because cleanup only ran on success.",
                "Removed verified orphaned files and added cleanup on failure with an age-based sweep.",
                "temporary-file-retention",
            ),
            Scenario(
                "Storage full because local backups exceed retention",
                "Application writes failed while old backup archives occupied most of the volume.",
                "The backup job created archives without removing copies past the retention window.",
                "Verified remote backup copies, removed expired local archives, and enforced backup retention.",
                "backup-retention",
            ),
        ),
        contexts=(
            Context("daily processing", "Daily processing in {service} could not persist outputs.",
                    "Verified daily outputs and free storage through {service}."),
            Context("tenant exports", "Tenant exports in {service} could not persist output files.",
                    "Verified tenant export writes and free storage through {service}."),
            Context("retention processing", "Retention processing in {service} could not write its progress files.",
                    "Verified retention progress and storage headroom through {service}."),
            Context("recovery replay", "Recovery replay in {service} could not persist replay results.",
                    "Verified recovery replay writes and storage headroom through {service}."),
            Context("scheduled archival", "Scheduled archival in {service} could not write new archives.",
                    "Verified archive creation and storage headroom through {service}."),
        ),
    ),
    IncidentFamily(
        services=("catalog-api", "inventory-api", "pricing-api"),
        severities=("SEV2", "SEV3", "SEV4"),
        tags=("cache", "latency", "database"),
        scenarios=(
            Scenario(
                "Cache stampede increases database latency",
                "Cache hits collapsed as popular entries expired simultaneously and database reads surged.",
                "Identical TTLs triggered concurrent refreshes of the same popular keys.",
                "Added TTL jitter and single-flight refresh, then warmed popular cache entries.",
                "cache-expiry",
            ),
            Scenario(
                "Cold cache namespace increases database latency after deployment",
                "Cache misses and database reads increased immediately after rollout.",
                "A deployment changed the cache key namespace without warming the replacement keys.",
                "Restored the compatible namespace, warmed replacement keys, and staged the namespace transition.",
                "cache-namespace",
            ),
            Scenario(
                "Cache eviction pressure increases database read latency",
                "Popular entries were repeatedly evicted and reloaded from the database.",
                "An oversized cache payload rollout exceeded the cache memory budget.",
                "Reduced cached payload sizes, applied a tested memory budget, and verified eviction rates stabilized.",
                "cache-eviction",
            ),
        ),
        contexts=(
            Context("product lookups", "Product lookup requests to {service} showed the regression.",
                    "Verified product lookup latency and cache hit rate in {service}."),
            Context("batch reads", "Batch read requests to {service} showed the regression.",
                    "Verified batch latency and cache hit rate in {service}."),
            Context("regional storefront", "Regional storefront requests to {service} showed the regression.",
                    "Verified regional storefront latency and cache hit rate in {service}."),
            Context("preview requests", "Preview requests to {service} showed the regression.",
                    "Verified preview latency and cache hit rate in {service}."),
            Context("snapshot reads", "Snapshot read requests to {service} showed the regression.",
                    "Verified snapshot latency and cache hit rate in {service}."),
        ),
    ),
    IncidentFamily(
        services=("notifications-worker", "webhooks-worker", "sync-worker"),
        severities=("SEV2", "SEV3", "SEV4"),
        tags=("rate-limit", "http-429"),
        scenarios=(
            Scenario(
                "Provider rate limits amplified by immediate retries",
                "HTTP 429 responses increased while rejected requests were immediately resubmitted.",
                "The retry loop ignored Retry-After and did not apply backoff.",
                "Honored Retry-After and added bounded exponential backoff with jitter.",
                "retry-backoff",
            ),
            Scenario(
                "Parallel delivery exceeds provider rate limits",
                "Provider HTTP 429 responses rose as delivery concurrency increased.",
                "A fanout change removed the shared per-provider concurrency limit.",
                "Restored the shared concurrency limit and verified delivery stayed within the provider quota.",
                "delivery-concurrency",
            ),
            Scenario(
                "Duplicate deliveries exhaust provider rate limits",
                "Repeated event IDs consumed the provider request allowance and triggered HTTP 429 responses.",
                "Redelivered events bypassed the event-ID deduplication check.",
                "Restored event-ID deduplication and verified replayed events did not trigger duplicate deliveries.",
                "duplicate-delivery",
            ),
        ),
        contexts=(
            Context("scheduled delivery", "Scheduled deliveries from {service} were delayed.",
                    "Verified the next scheduled delivery cycle from {service}."),
            Context("bulk partner synchronization", "Bulk partner synchronization from {service} was delayed.",
                    "Verified bulk partner synchronization from {service}."),
            Context("retry recovery", "Retry recovery in {service} delayed outbound deliveries.",
                    "Verified retry recovery completed through {service}."),
            Context("regional replay", "Regional event replay through {service} was delayed.",
                    "Verified regional replay completion through {service}."),
            Context("burst fanout", "Burst event fanout through {service} was delayed.",
                    "Verified burst fanout stayed within provider limits through {service}."),
        ),
    ),
    IncidentFamily(
        services=("reports-worker", "exports-worker", "analytics-worker"),
        severities=("SEV2", "SEV3", "SEV4"),
        tags=("memory", "export", "oom"),
        scenarios=(
            Scenario(
                "Export buffering exhausts worker memory",
                "Large exports exceeded the container memory limit and were killed.",
                "The export implementation buffered the entire result set in memory.",
                "Replaced whole-result buffering with bounded streaming batches and reran interrupted exports.",
                "export-buffering",
            ),
            Scenario(
                "Retained export artifacts exhaust worker memory",
                "Memory usage increased after each completed export until the worker restarted.",
                "A process-local artifact cache retained export buffers without eviction.",
                "Released completed export buffers and added bounded cache eviction.",
                "artifact-cache",
            ),
            Scenario(
                "Concurrent exports exceed the worker memory budget",
                "Individual exports succeeded but overlapping jobs exceeded the memory limit.",
                "The scheduler admitted too many memory-intensive exports to each worker.",
                "Limited concurrent exports per worker and verified the combined memory budget under load.",
                "export-concurrency",
            ),
        ),
        contexts=(
            Context("daily exports", "Daily export jobs in {service} were interrupted.",
                    "Verified daily export completion and peak memory in {service}."),
            Context("historical reprocessing", "Historical reprocessing exports in {service} were interrupted.",
                    "Verified historical export completion and peak memory in {service}."),
            Context("large tenant reports", "Large tenant report exports in {service} were interrupted.",
                    "Verified large tenant report completion and peak memory in {service}."),
            Context("analytics reconciliation", "Analytics reconciliation exports in {service} were interrupted.",
                    "Verified analytics reconciliation completion and peak memory in {service}."),
            Context("multi-account exports", "Multi-account exports in {service} were interrupted.",
                    "Verified multi-account export completion and peak memory in {service}."),
        ),
    ),
    IncidentFamily(
        services=("orders-api", "billing-api", "catalog-api"),
        severities=("SEV1", "SEV2", "SEV3"),
        tags=("database", "migration", "http-500"),
        scenarios=(
            Scenario(
                "HTTP 500 after a required column migration is missed",
                "Queries failed with column-does-not-exist errors after release.",
                "The application was deployed before its backward-compatible column migration ran.",
                "Rolled back the application, applied the missing migration, and redeployed after verifying the schema.",
                "missing-column",
            ),
            Scenario(
                "HTTP 500 after a NOT NULL migration breaks existing writers",
                "Inserts failed because a newly required database field was absent.",
                "A NOT NULL constraint was enabled while older application instances still omitted the field.",
                "Reverted the constraint, deployed compatible writers, backfilled values, and reapplied the constraint after verification.",
                "not-null-rollout",
            ),
            Scenario(
                "HTTP 500 after a column rename breaks mixed versions",
                "Older instances failed queries against a column removed by migration.",
                "A direct column rename removed the old name before older instances were retired.",
                "Restored a compatibility column, synchronized values, and staged the rename across application versions.",
                "column-rename",
            ),
        ),
        contexts=ROLLOUT_CONTEXTS,
    ),
    IncidentFamily(
        services=("inventory-api", "catalog-api", "orders-api"),
        severities=("SEV2", "SEV3", "SEV4"),
        tags=("database", "index", "latency"),
        scenarios=(
            Scenario(
                "Missing database index slows filtered lookups",
                "Lookup latency and database CPU increased as the table grew.",
                "The lookup filter key had no supporting index, requiring full table scans.",
                "Added the filter-key index and verified the query plan stopped scanning the entire table.",
                "missing-index",
            ),
            Scenario(
                "A function-wrapped database filter bypasses its index",
                "Filtered lookups scanned the table even though an index existed.",
                "A function applied to the indexed column prevented the lookup from using that index.",
                "Rewrote the predicate to use the indexed value and verified indexed access in the query plan.",
                "function-filter",
            ),
            Scenario(
                "Composite database index order slows lookups",
                "Filtered lookups scanned many rows before applying the lookup key.",
                "The composite index placed a range column before the selective equality filter key.",
                "Added a composite index with the equality key before the range column and verified reduced rows scanned.",
                "index-column-order",
            ),
        ),
        contexts=(
            Context("tenant filtering", "Tenant-filtered GET /{resource} requests were slow.",
                    "Verified tenant-filtered latency and rows scanned through {service}."),
            Context("status filtering", "Status-filtered GET /{resource} requests were slow.",
                    "Verified status-filtered latency and rows scanned through {service}."),
            Context("region filtering", "Region-filtered GET /{resource} requests were slow.",
                    "Verified region-filtered latency and rows scanned through {service}."),
            Context("customer filtering", "Customer-filtered GET /{resource} requests were slow.",
                    "Verified customer-filtered latency and rows scanned through {service}."),
            Context("warehouse filtering", "Warehouse-filtered GET /{resource} requests were slow.",
                    "Verified warehouse-filtered latency and rows scanned through {service}."),
        ),
    ),
)


def dataset_capacity() -> int:
    """Maximum samples with balanced families and no repeated narratives."""
    return len(FAMILIES) * min(
        len(family.services) * len(family.scenarios) * len(family.contexts)
        for family in FAMILIES
    )


def generate_incidents(num_sample: int = DEFAULT_NUM_SAMPLE) -> list[dict[str, object]]:
    """Sample service/scenario/context combinations without replacement."""
    if num_sample < 0:
        raise ValueError("num_sample must be non-negative")
    capacity = dataset_capacity()
    if num_sample > capacity:
        raise ValueError(f"num_sample exceeds the available {capacity} unique balanced samples")
    rng = random.Random(SEED)
    pools = []
    for family in FAMILIES:
        scenario_pools = []
        for _ in family.scenarios:
            combinations = [(service, context) for service in family.services for context in family.contexts]
            rng.shuffle(combinations)
            scenario_pools.append(combinations)
        pools.append(scenario_pools)

    date_range_seconds = int((END_DATE - START_DATE).total_seconds())
    incidents = []
    for index in range(num_sample):
        family_index = index % len(FAMILIES)
        family = FAMILIES[family_index]
        scenario_index = (index // len(FAMILIES)) % len(family.scenarios)
        scenario = family.scenarios[scenario_index]
        service, context = pools[family_index][scenario_index].pop()
        replacements = {"service": service, "resource": service.split("-")[0]}
        created_at = START_DATE + timedelta(seconds=rng.randrange(date_range_seconds))
        incidents.append({
            "id": f"INC-{index + 1:04d}",
            "created_at": created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "environment": rng.choice(ENVIRONMENTS),
            "service": service,
            "severity": rng.choice(family.severities),
            "title": f"{service}: {scenario.title} — {context.label}",
            "description": f"{context.description.format(**replacements)} {scenario.symptom} Root cause: {scenario.cause}",
            "resolution_summary": f"{scenario.resolution} {context.verification.format(**replacements)}",
            "tags": [*family.tags, scenario.tag],
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
    try:
        main(num_sample=args.num_sample)
    except ValueError as exc:
        parser.error(str(exc))
