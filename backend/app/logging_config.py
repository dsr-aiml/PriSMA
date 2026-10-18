import json
import logging
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    def format(self, record):
        body = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("investigation_id", "stage", "request_id", "status_code"):
            if hasattr(record, key):
                body[key] = getattr(record, key)
        # Credentials and request bodies are never logged. Tracebacks remain local worker diagnostics.
        if record.exc_info:
            body["exception"] = self.formatException(record.exc_info)
        return json.dumps(body)


def configure_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
