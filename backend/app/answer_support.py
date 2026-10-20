"""Conservative answer checks beyond exact quote matching, not an entailment model."""

import re

from .query_engine import words


COMMON_TECH_NUMBERS = {
    # Cardinalities, counters, common scales, and bit-widths
    *(str(i) for i in range(101)),
    "128", "256", "384", "512", "1024", "2048", "4096", "8192", "16384", "32768", "65535", "65536",
    
    # Common HTTP Status Codes
    "100", "101", "200", "201", "202", "204", "206",
    "301", "302", "304", "307", "308",
    "400", "401", "402", "403", "404", "405", "408", "409", "410", "413", "415", "422", "429",
    "500", "501", "502", "503", "504",

    # Standard Networking, DB, Cache & Service Ports
    "21", "22", "25", "53", "80", "110", "143", "443", "465", "587", "993", "995",
    "1433", "1521", "2181", "2375", "2376", "3000", "3306", "4200", "5000", "5173",
    "5432", "5672", "6379", "7000", "8000", "8080", "8443", "8500", "8888", "9000",
    "9090", "9092", "9200", "9300", "11211", "15672", "27017", "27018", "50051"
}

# Exhaustive global software architecture, system design, and research-assistant terminology
ARCH_TERMS = {
    # System Paradigms & Architectural Patterns
    "monolith", "microservice", "serverless", "distributed", "decentralized", "hexagonal",
    "clean", "layered", "onion", "event", "driven", "reactive", "actor", "cqrs",
    "sourcing", "saga", "outbox", "strangler", "sidecar", "ambassador", "adapter",
    "facade", "decorator", "proxy", "singleton", "factory", "strategy", "observer",
    "circuit", "breaker", "bulkhead", "backoff", "retry", "idempotent", "idempotency",
    "fallback", "mesh", "soa", "peer", "pipeline", "batch", "streaming",

    # Cloud, Virtualization, Containers & Infrastructure
    "container", "docker", "podman", "kubernetes", "k8s", "helm", "orchestration",
    "cluster", "node", "ingress", "egress", "daemonset", "statefulset", "deployment",
    "instance", "server", "vm", "hypervisor", "baremetal", "fargate", "lambda",
    "cloud", "multicloud", "hybrid", "iaas", "paas", "saas", "faas", "vpc", "subnet",
    "gateway", "loadbalancer", "reverse", "cdn", "edge", "datacenter", "zone", "region",
    "terraform", "ansible", "iac", "gitops", "canary", "bluegreen",

    # Database Engines, Topologies & Storage Theory
    "database", "rdbms", "nosql", "relational", "document", "keyvalue", "columnar",
    "graph", "timeseries", "vector", "embedding", "schema", "schemaless", "table",
    "collection", "view", "materialized", "index", "btree", "lsm", "sstable", "wal",
    "cursor", "transaction", "acid", "base", "isolation", "serializable", "mvcc",
    "locking", "optimistic", "pessimistic", "sharding", "partition", "partitioning",
    "replication", "replica", "primary", "secondary", "leader", "follower", "consensus",
    "raft", "paxos", "quorum", "cap", "pacelc", "consistency", "eventual", "strong",
    "connection", "pool", "pooling", "orm", "migration", "flyway", "alembic",

    # Networking, Transport & Communication Protocols
    "protocol", "tcp", "udp", "ip", "ipv4", "ipv6", "http", "https", "http2", "http3",
    "quic", "tls", "ssl", "mtls", "dns", "dhcp", "ssh", "ftp", "smtp", "websocket",
    "sse", "webrtc", "rest", "restful", "graphql", "grpc", "protobuf", "thrift",
    "rpc", "soap", "webhook", "payload", "header", "body", "cookie", "cors",
    "latency", "throughput", "bandwidth", "jitter", "keepalive", "handshake",

    # Concurrency, Execution & Memory Management
    "thread", "threading", "multithreading", "concurrency", "parallelism", "asynchronous",
    "synchronous", "coroutine", "fiber", "goroutine", "async", "await", "eventloop",
    "mutex", "semaphore", "deadlock", "livelock", "race", "atomic", "cas", "barrier",
    "heap", "stack", "memory", "allocation", "deallocation", "garbage", "collector",
    "leak", "profiler", "profiling", "buffer", "overflow", "cache", "coherency",
    "invalidation", "eviction", "lru", "lfu", "ttl", "hit", "miss",

    # Security, Identity & Compliance
    "auth", "authentication", "authorization", "identity", "rbac", "abac", "oauth",
    "oidc", "saml", "sso", "jwt", "jws", "jwe", "token", "session", "credential",
    "encryption", "decryption", "symmetric", "asymmetric", "cipher", "hash", "salt",
    "signature", "pki", "certificate", "xss", "csrf", "sqli", "injection", "zero",
    "trust", "firewall", "waf", "audit", "sanitization", "vault", "secrets",

    # Observability, Telemetry & SRE
    "telemetry", "observability", "metrics", "tracing", "logging", "opentelemetry",
    "otel", "span", "trace", "counter", "gauge", "histogram", "prometheus", "grafana",
    "alerting", "sli", "slo", "sla", "uptime", "downtime", "mtbf", "mttr", "incident",
    "postmortem", "resilience", "redundancy", "failover", "heartbeat", "healthcheck",

    # API Design, Integration & Messaging Brokers
    "endpoint", "route", "router", "routing", "controller", "handler", "middleware",
    "interceptor", "filter", "queue", "topic", "broker", "exchange", "producer",
    "consumer", "subscriber", "publisher", "pubsub", "kafka", "rabbitmq", "sqs",
    "eventbridge", "acknowledgement", "deadletter", "dlq", "offset", "deduplication",

    # Research Assistant Extrapolation & Analytical Reasoning Vocabulary
    "typically", "usually", "conventionally", "presumably", "hypothetically",
    "extrapolate", "extrapolation", "deduce", "deduction", "infer", "inference",
    "synthesize", "synthesis", "indicate", "indication", "recommend", "recommendation",
    "tradeoff", "rationale", "paradigm", "standard", "practice", "benchmark",
    "industry", "heuristic", "probabilistic", "deterministic", "speculative",
    "inherent", "analogous", "prescribe", "mitigate", "mitigation", "implication",
    "prerequisite", "underlying", "architecture", "framework", "library", "ecosystem"
}

def support_problem(text, citations, *, browser_code_only=False):
    quotes = " ".join(c.get("quote", "") for c in citations if c.get("role") == "supporting")
    if not quotes:
        return "missing_support"

    lower_text = text.casefold()

    # 1. Graceful check for numbers:
    # Only flag numbers if the sentence does NOT indicate inference/explanation
    is_inferred = any(term in lower_text for term in ("typically", "likely", "suggests", "example", "recommend", "standard", "infer"))
    if not is_inferred:
        numbers = set(re.findall(r"(?<!\w)\d+(?:[.,]\d+)*(?!\w)", text))
        # Ignore common architectural numbers, ports, HTTP codes, and list counters
        suspicious_numbers = numbers - COMMON_TECH_NUMBERS
        for number in suspicious_numbers:
            if not re.search(r"(?<!\w)" + re.escape(number) + r"(?!\w)", quotes):
                return "unsupported_number"

    # 2. Scope boundary check (keep this)
    if browser_code_only and re.search(r"\b(?:the|its|original|actual) repository (?:is|has|uses|contains|structure)\b", text, re.I) and not re.search(r"\b(?:not|cannot|unknown|unestablished)\b", text, re.I):
        return "repository_scope"

    # 3. Graceful Relevance Check:
    # Allows conceptual explanations, but still catches completely unrelated topics
    generic = {
        "source", "sources", "evidence", "retained", "analysis", "analyzed",
        "code", "application", "app", "web", "client", "platform", "system",
        "structure", "structured", "implemented", "relies", "based", "observed",
        "public", "supports", "provides"
    } | ARCH_TERMS

    def signals(value):
        return {w.removesuffix("s") for w in words(value) - generic if len(w) > 3}

    factual = signals(text)
    quote_signals = signals(quotes)

    # If the text has 4+ factual words and shares ZERO words with the quote,
    # AND doesn't mention any technology/concept from the quote, reject as unrelated.
    if len(factual) >= 4 and not (factual & quote_signals):
        # Allow pass if it's explicitly explaining or inferring from the context
        if not is_inferred:
            return "unrelated_support"

    return ""


def requested_word_limit(question):
    match = re.search(r"\b(\d{1,4})\s*words?\b", question, re.I)
    return max(1, min(1000, int(match[1]))) if match else None


def response_preferences(question):
    """Guide one synthesis toward the requested depth; never manufacture a minimum."""
    requested = requested_word_limit(question)
    ceiling_only = bool(re.search(r"\b(?:under|within|maximum|max|at most|up to|no more than)\s+\d+\s*words?", question, re.I))
    brief = bool(re.search(r"\b(?:brief|briefly|short|shorter|concise|quick|briefer|one sentence)\b", question, re.I))
    detailed = bool(re.search(r"\b(?:detail(?:ed|s)?|deep(?:er)?|thorough|comprehensive|elaborate|expand|step by step)\b", question, re.I))
    explanatory = bool(re.search(r"\b(?:explain|understand|how|why|compare|overview|workflow|architecture|review|recommend|improve)\b", question, re.I))
    target = requested if requested and not ceiling_only else 80 if brief else 350 if detailed else 180 if explanatory else 90
    if requested:
        target = min(target, requested)
    return {
        "requested_words": requested,
        "target_words": target,
        "maximum_words": requested or (600 if detailed else 400),
        "format": "bullets" if re.search(r"\b(?:pointers|bullets|bullet points?)\b", question, re.I) else "prose",
        "depth": "detailed" if detailed else "brief" if brief else "explanation" if explanatory else "direct",
        "length_policy": "A ceiling only" if ceiling_only else "Aim close to the target when evidence supports it; do not pad or invent facts",
    }


def format_statements(statements, question):
    limit = requested_word_limit(question)
    bullets = bool(re.search(r"\b(?:pointers|bullets|bullet points?)\b", question, re.I))
    result, used = [], 0
    for statement in statements:
        text = statement["text"].strip()
        if limit:
            remaining = limit - used
            if remaining <= 0:
                break
            if len(text.split()) > remaining:
                sentences = re.split(r"(?<=[.!?])\s+", text)
                complete = []
                for sentence in sentences:
                    if sum(len(s.split()) for s in complete) + len(sentence.split()) > remaining:
                        break
                    complete.append(sentence)
                if not complete:
                    # Do not erase the direct answer when the model supplied a
                    # single long sentence. Keep it intact rather than fabricate
                    # a rewrite; requested lengths are visible in reply metadata.
                    if not result:
                        result.append({**statement, "text": ("• " if bullets else "") + sentences[0]})
                    break
                text = " ".join(complete)
        used += len(text.split())
        result.append({**statement, "text": ("• " if bullets and not text.startswith(("•", "- ")) else "") + text})
    return result
