"""Atomic rolling request/input budget for this server's hosted Research calls.

Google quotas are per project. Configure the shared project label and actual
limits; the ledger cannot observe traffic from unrelated applications.
"""

import hashlib
import time
import uuid

from redis import Redis

from .config import settings

RESERVE = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2])/1000000
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now-60)
local rows = redis.call('ZRANGE', KEYS[1], 0, -1, 'WITHSCORES')
local total = 0
for i=1,#rows,2 do total = total + tonumber(string.match(rows[i], ':(%d+)$')) end
local wait = 0
if #rows/2 >= tonumber(ARGV[1]) then wait = math.max(0, tonumber(rows[2])+60-now) end
local remaining = total + tonumber(ARGV[3])
for i=1,#rows,2 do
  if remaining <= tonumber(ARGV[2]) then break end
  remaining = remaining - tonumber(string.match(rows[i], ':(%d+)$'))
  wait = math.max(wait, tonumber(rows[i+1])+60-now)
end
if wait > 0 then return tostring(wait) end
redis.call('ZADD', KEYS[1], now, ARGV[4]..':'..ARGV[3])
redis.call('EXPIRE', KEYS[1], 120)
return '0'
"""


def admit(tokens, deadline, *, connection=None, sleeper=time.sleep, clock=time.monotonic):
    from .model_gateway import ModelFailure

    cfg = settings()
    if tokens > cfg.gemini_query_input_tpm:
        raise ModelFailure(
            "The selected context exceeds the configured input allowance. Reduce context or adjust the server budget to the project's actual quota.",
            code="input_budget",
        )
    connection = connection or Redis.from_url(cfg.redis_url, socket_timeout=3, socket_connect_timeout=3)
    identity = cfg.gemini_quota_project or hashlib.sha256(cfg.gemini_api_key.encode()).hexdigest()
    key = (
        "prisma:research-budget:"
        + hashlib.sha256((identity + ":" + cfg.gemini_query_model).encode()).hexdigest()
    )
    waited = 0.0
    while clock() < deadline:
        try:
            delay = float(
                connection.eval(
                    RESERVE,
                    1,
                    key,
                    cfg.gemini_query_rpm,
                    cfg.gemini_query_input_tpm,
                    tokens,
                    uuid.uuid4().hex,
                )
            )
        except Exception as exc:
            raise ModelFailure(
                "Research request scheduling is unavailable. Check Redis.", code="scheduling_unavailable"
            ) from exc
        if delay <= 0:
            return round(waited, 3)
        delay = min(delay + 0.05, 10)
        if clock() + delay >= deadline or waited + delay > cfg.research_max_wait_seconds:
            raise ModelFailure(
                "Research is waiting for the configured request allowance. Try again shortly.",
                code="quota_wait",
            )
        sleeper(delay)
        waited += delay
    raise ModelFailure("Research reached its scheduling deadline.", code="quota_wait")
