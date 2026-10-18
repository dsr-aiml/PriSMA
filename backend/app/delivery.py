"""Conservative, owner-routed RQ delivery inspection. Missing records are unknown."""
from redis import Redis
from .config import settings


def delivery_state(identifier):
    connection = Redis.from_url(settings().redis_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        connection.ping()
        keys = []
        exact = "rq:job:" + identifier
        if connection.exists(exact):
            keys.append(exact)
        for key in connection.scan_iter(match=exact + "-*", count=25):
            keys.append(key)
            if len(keys) > 24:
                return {"available": True, "state": "unknown", "recoverable": False, "reason": "Delivery history exceeds the inspection window."}
        if not keys:
            return {"available": True, "state": "unknown", "recoverable": False, "reason": "No retained queue delivery record. Inspect the worker before retrying."}
        states = {connection.hget(key, "status") for key in keys}
        states = {value.decode() if isinstance(value, bytes) else value for value in states}
        active = states & {"queued", "started", "deferred", "scheduled"}
        if active:
            return {"available": True, "state": "active", "recoverable": False, "reason": "The queue still records active work.", "deliveries": sorted(active)}
        terminal = {"finished", "failed", "stopped", "canceled", "cancelled"}
        recoverable = bool(states) and states <= terminal
        return {"available": True, "state": "ended" if recoverable else "unknown", "recoverable": recoverable,
                "reason": "Recorded deliveries ended." if recoverable else "Delivery status is not established.", "deliveries": sorted(value for value in states if isinstance(value, str))}
    except Exception:
        return {"available": False, "state": "unavailable", "recoverable": False, "reason": "Queue inspection is unavailable. Saved records are intact."}
    finally:
        connection.close()
