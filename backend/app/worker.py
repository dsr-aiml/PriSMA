from redis import Redis
from rq import Queue, Worker
from rq.serializers import JSONSerializer

from .config import settings
from .logging_config import configure_logging
import os

if __name__ == "__main__":
    configure_logging()
    connection = Redis.from_url(settings().redis_url)
    names = [value.strip() for value in os.environ.get("WORKER_QUEUES", "investigations").split(",") if value.strip()]
    queues = [Queue(name, connection=connection, serializer=JSONSerializer) for name in names]
    Worker(queues, connection=connection, serializer=JSONSerializer).work()
