"""Shared RQ queue wiring.

The webhook receiver enqueues lead-processing jobs here; the `rq worker pipeline`
systemd service (see deploy.sh) consumes them out-of-process so jobs survive a
web-server restart and get retried on failure.
"""
from redis import Redis
from rq import Queue, Retry
from config import REDIS_URL

# Queue name must match the worker invocation: `rq worker pipeline`.
QUEUE_NAME = "pipeline"

redis_conn = Redis.from_url(REDIS_URL)
pipeline_queue = Queue(QUEUE_NAME, connection=redis_conn)


def enqueue_pipeline(lead_id: str):
    """Enqueue a lead for asynchronous pipeline processing.

    Transient failures (LLM/Tavily/network) are retried with backoff. After the
    retries are exhausted the job lands in RQ's FailedJobRegistry (the dead-letter
    queue) where it can be inspected and requeued, rather than being lost.
    """
    return pipeline_queue.enqueue(
        "workers.pipeline.run_pipeline",
        lead_id,
        job_id=f"lead:{lead_id}",  # idempotent: re-enqueueing the same lead replaces it
        retry=Retry(max=3, interval=[30, 120, 300]),
        job_timeout=600,
    )
