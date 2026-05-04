"""RAG Kafka producer — publishes LLM task messages.

Falls back to direct daemon-thread execution when Kafka is unavailable.
"""
import json
import threading
from datetime import datetime, timezone

from framework.commons.logger import logger
from src.config import Config

_producer = None
_producer_lock = threading.Lock()
_kafka_ok: bool | None = None   # None = untested


def _make_producer():
    """Try to create a producer using framework helpers, else kafka-python directly."""
    try:
        from framework.etl.framework_etl import create_kafka_producer
        return create_kafka_producer(Config.KAFKA_BOOTSTRAP_SERVERS)
    except Exception:
        # Fallback: plain kafka-python (framework may have Redis issues in tests)
        from kafka import KafkaProducer
        return KafkaProducer(
            bootstrap_servers=Config.KAFKA_BOOTSTRAP_SERVERS.split(","),
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            acks=1,
            retries=3,
            request_timeout_ms=5000,
        )


def get_producer():
    global _producer, _kafka_ok
    if _producer is not None:
        return _producer
    with _producer_lock:
        if _producer is not None:
            return _producer
        try:
            _producer = _make_producer()
            _kafka_ok = True
            logger.info(f"[kafka] Producer connected → {Config.KAFKA_BOOTSTRAP_SERVERS}")
        except Exception as e:
            _kafka_ok = False
            logger.warning(f"[kafka] Producer unavailable (fallback to threads): {e}")
    return _producer


def publish_task(task: dict) -> bool:
    """Publish a task dict to the appropriate Kafka topic.

    Returns True if Kafka delivery succeeded, False if fallback was used.
    """
    task = dict(task)
    task.setdefault("created_at", datetime.now(timezone.utc).isoformat())

    # Route fast vs LLM tasks to separate topics. ``embed_file`` rides the
    # LLM lane because it's CPU-heavy (fastembed) and benefits from the
    # same concurrency cap as the LLM tasks — running 10 file embeddings
    # in parallel just thrashes the CPU.
    llm_types = {"insight_ai", "enrich_doc", "enrich_field", "embed_docs", "embed_file"}
    topic = (
        Config.KAFKA_TOPIC_LLM_TASKS
        if task.get("task_type") in llm_types
        else Config.KAFKA_TOPIC_FAST_TASKS
    )

    producer = get_producer()
    if producer is None:
        _fallback_thread(task)
        return False

    try:
        key = task.get("datasource", "default")
        fut = producer.send(topic, value=task, key=key.encode() if isinstance(key, str) else key)
        producer.flush(timeout=5)
        logger.debug(f"[kafka] → {topic} {task.get('task_type')} ds={task.get('datasource')}")
        return True
    except Exception as e:
        logger.error(f"[kafka] Publish failed ({e}), using thread fallback")
        _fallback_thread(task)
        return False


def _fallback_thread(task: dict) -> None:
    """Run the task directly in a daemon thread when Kafka is unavailable."""
    from src.tasking.handlers import dispatch_task
    t = threading.Thread(target=dispatch_task, args=(task,), daemon=True)
    t.start()
    logger.debug(f"[kafka-fallback] Thread started for {task.get('task_type')}")
