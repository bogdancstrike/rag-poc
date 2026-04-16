"""Kafka consumer worker for RAG LLM tasks.

Concurrency model:
  LLM tasks  — semaphore-limited (LLM_PARALLEL slots). Each task runs in its own
               daemon thread. On timeout the semaphore is released explicitly so
               new tasks can start even if the stuck thread is still alive.
  Fast tasks — unbounded ThreadPoolExecutor (coordinators + stats, near-instant).
"""
import json
import threading
from concurrent.futures import ThreadPoolExecutor

from framework.commons.logger import logger
from src.config import Config
from src.worker.task_handlers import dispatch_task, mark_task_error

# Watchdog deadline: a bit more than the LLM HTTP timeout so the HTTP client
# has a chance to raise its own timeout first.
_LLM_TASK_TIMEOUT = Config.LLM_TIMEOUT + 30

_LLM_TYPES  = {"insight_ai", "enrich_doc", "enrich_field", "embed_docs"}
_FAST_TYPES = {"insight_coordinator", "insight_stats"}

_consumer_thread: threading.Thread | None = None
_fast_executor:   ThreadPoolExecutor | None = None
_llm_semaphore:   threading.Semaphore | None = None
_stop_event = threading.Event()


def start_consumer() -> bool:
    """Start Kafka consumer in a background daemon thread.
    Returns True on success, False if Kafka unavailable.
    """
    global _consumer_thread, _fast_executor, _llm_semaphore

    _llm_semaphore = threading.Semaphore(Config.LLM_PARALLEL)
    _fast_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="fast-worker")
    _stop_event.clear()

    _consumer_thread = threading.Thread(target=_consumer_loop, daemon=True, name="kafka-consumer")
    _consumer_thread.start()
    logger.info(
        f"[kafka] Consumer started topic_llm={Config.KAFKA_TOPIC_LLM_TASKS} "
        f"topic_fast={Config.KAFKA_TOPIC_FAST_TASKS} "
        f"group={Config.KAFKA_CONSUMER_GROUP} LLM_PARALLEL={Config.LLM_PARALLEL}"
    )
    return True


def stop_consumer() -> None:
    _stop_event.set()


def _route(task: dict) -> None:
    ttype = task.get("task_type", "")
    is_llm = ttype in _LLM_TYPES
    pool = "llm" if is_llm else "fast"
    logger.info(
        f"[kafka] → submit task_type={ttype} ds={task.get('datasource')} pool={pool}_executor",
        "green",
    )
    if is_llm:
        _dispatch_llm(task)
    else:
        _fast_executor.submit(dispatch_task, task)


def _dispatch_llm(task: dict) -> None:
    """Run an LLM task in a daemon thread, gated by the semaphore.

    A separate acquirer thread waits for a semaphore slot so the consumer loop
    is never blocked.  Once the slot is acquired, the actual worker thread
    starts.  A watchdog thread gives the worker _LLM_TASK_TIMEOUT seconds; on
    expiry it releases the semaphore (so the next queued task can start) and
    marks the DB row as error — the stuck thread is left to finish on its own.
    """
    def _acquire_then_run():
        _llm_semaphore.acquire()          # blocks until a slot is free
        released = threading.Event()

        def _worker():
            try:
                dispatch_task(task)
            finally:
                # Release only if the watchdog hasn't already done so.
                if not released.is_set():
                    released.set()
                    _llm_semaphore.release()

        def _watchdog():
            worker.join(timeout=_LLM_TASK_TIMEOUT)
            if worker.is_alive():
                ttype = task.get("task_type", "")
                ds    = task.get("datasource", "?")
                logger.error(
                    f"[kafka] ✗ timeout task_type={ttype} ds={ds} "
                    f"after {_LLM_TASK_TIMEOUT}s — marking error"
                )
                # Release semaphore before marking DB so the next task can start
                # immediately without waiting for the stuck thread to finish.
                if not released.is_set():
                    released.set()
                    _llm_semaphore.release()
                mark_task_error(task, f"Task timed out after {_LLM_TASK_TIMEOUT}s")

        worker = threading.Thread(target=_worker, daemon=True, name=f"llm-{task.get('task_type')}")
        worker.start()
        threading.Thread(target=_watchdog, daemon=True, name=f"llm-watchdog-{task.get('task_type')}").start()

    threading.Thread(target=_acquire_then_run, daemon=True, name="llm-acquirer").start()


def _consumer_loop() -> None:
    try:
        _make_consumer_and_run()
    except Exception as e:
        logger.error(f"[kafka] Consumer loop crashed: {e}", exc_info=True)


def _make_consumer_and_run() -> None:
    try:
        from framework.etl.framework_etl import create_kafka_consumer
        consumer = create_kafka_consumer(
            [Config.KAFKA_TOPIC_LLM_TASKS, Config.KAFKA_TOPIC_FAST_TASKS],
            Config.KAFKA_BOOTSTRAP_SERVERS,
            enable_auto_commit=True,
        )
    except Exception:
        from kafka import KafkaConsumer
        from kafka.errors import NoBrokersAvailable
        try:
            consumer = KafkaConsumer(
                Config.KAFKA_TOPIC_LLM_TASKS,
                Config.KAFKA_TOPIC_FAST_TASKS,
                bootstrap_servers=Config.KAFKA_BOOTSTRAP_SERVERS.split(","),
                group_id=Config.KAFKA_CONSUMER_GROUP,
                auto_offset_reset="earliest",
                enable_auto_commit=True,
                value_deserializer=lambda v: json.loads(v.decode("utf-8")),
                consumer_timeout_ms=500,
            )
        except NoBrokersAvailable:
            logger.warning("[kafka] No brokers available — consumer not started")
            return

    logger.info(f"[kafka] Subscribed to {Config.KAFKA_TOPIC_LLM_TASKS}, {Config.KAFKA_TOPIC_FAST_TASKS}")
    try:
        while not _stop_event.is_set():
            try:
                records = consumer.poll(timeout_ms=500)
                for tp, messages in records.items():
                    for msg in messages:
                        raw = msg.value
                        task = raw if isinstance(raw, dict) else json.loads(raw)
                        logger.info(
                            f"[kafka] ← received task_type={task.get('task_type')} "
                            f"ds={task.get('datasource')} "
                            f"topic={tp.topic} partition={tp.partition} offset={msg.offset}",
                            "green",
                        )
                        _route(task)
            except StopIteration:
                pass
    finally:
        consumer.close()
        logger.info("[kafka] Consumer closed")
