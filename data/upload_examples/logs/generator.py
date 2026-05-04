#!/usr/bin/env python3

import argparse
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from faker import Faker


LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

SERVICES = [
    "auth-service",
    "user-service",
    "payment-service",
    "notification-service",
    "order-service",
    "inventory-service",
    "gateway",
    "search-service",
    "recommendation-service",
    "billing-service",
]

HTTP_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]

ENDPOINTS = [
    "/api/v1/login",
    "/api/v1/logout",
    "/api/v1/users",
    "/api/v1/users/{id}",
    "/api/v1/orders",
    "/api/v1/orders/{id}",
    "/api/v1/products",
    "/api/v1/products/{id}",
    "/api/v1/payments",
    "/api/v1/search",
    "/api/v1/notifications",
    "/health",
    "/metrics",
]

STATUS_CODES = [
    200, 200, 200, 200, 200,
    201, 204,
    400, 401, 403, 404,
    409, 422,
    500, 502, 503, 504,
]

ERROR_MESSAGES = [
    "Database connection timeout",
    "Kafka broker unavailable",
    "Redis cache miss",
    "Invalid authentication token",
    "Payment provider rejected transaction",
    "Elasticsearch query timeout",
    "Rate limit exceeded",
    "Unexpected null value",
    "Failed to deserialize request body",
    "External API returned invalid response",
]

INFO_MESSAGES = [
    "Request processed successfully",
    "User authenticated successfully",
    "Order created successfully",
    "Payment processed successfully",
    "Cache refreshed",
    "Message published to Kafka",
    "Background job completed",
    "Health check passed",
    "Search query executed",
    "Notification sent successfully",
]


def random_timestamp(start: datetime, end: datetime) -> datetime:
    """
    Generate a random timestamp between start and end.
    """
    delta = end - start
    random_seconds = random.randint(0, int(delta.total_seconds()))
    return start + timedelta(seconds=random_seconds)


def generate_log_line(fake: Faker, start: datetime, end: datetime) -> str:
    """
    Generate one fake log line.
    Format is JSON Lines compatible, one JSON object per row.
    """
    timestamp = random_timestamp(start, end).isoformat()

    level = random.choices(
        LOG_LEVELS,
        weights=[10, 60, 15, 12, 3],
        k=1,
    )[0]

    service = random.choice(SERVICES)
    method = random.choice(HTTP_METHODS)
    endpoint = random.choice(ENDPOINTS)

    if "{id}" in endpoint:
        endpoint = endpoint.replace("{id}", str(random.randint(1, 1_000_000)))

    status_code = random.choice(STATUS_CODES)

    if level in ["ERROR", "CRITICAL"] or status_code >= 500:
        message = random.choice(ERROR_MESSAGES)
    else:
        message = random.choice(INFO_MESSAGES)

    duration_ms = round(random.uniform(5, 3000), 2)

    user_id = random.randint(1, 1_000_000)
    request_id = str(uuid.uuid4())
    trace_id = fake.sha256()[:32]
    span_id = fake.sha1()[:16]
    ip = fake.ipv4_public()

    return (
        "{"
        f'"timestamp":"{timestamp}",'
        f'"level":"{level}",'
        f'"service":"{service}",'
        f'"message":"{message}",'
        f'"method":"{method}",'
        f'"endpoint":"{endpoint}",'
        f'"status_code":{status_code},'
        f'"duration_ms":{duration_ms},'
        f'"user_id":{user_id},'
        f'"request_id":"{request_id}",'
        f'"trace_id":"{trace_id}",'
        f'"span_id":"{span_id}",'
        f'"ip":"{ip}"'
        "}\n"
    )


def generate_logs(
    output_file: Path,
    rows: int,
    batch_size: int,
    days_back: int,
    seed: int | None = None,
) -> None:
    """
    Generate fake logs and write them to a file using buffered batches.
    """
    if seed is not None:
        random.seed(seed)
        Faker.seed(seed)

    fake = Faker()

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days_back)

    output_file.parent.mkdir(parents=True, exist_ok=True)

    written = 0

    with output_file.open("w", encoding="utf-8") as file:
        buffer = []

        for i in range(1, rows + 1):
            buffer.append(generate_log_line(fake, start, end))

            if len(buffer) >= batch_size:
                file.writelines(buffer)
                written += len(buffer)
                buffer.clear()

                print(f"Written {written:,}/{rows:,} rows")

        if buffer:
            file.writelines(buffer)
            written += len(buffer)

    print(f"Done. Generated {written:,} log rows into: {output_file}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate fake JSON log files using Faker."
    )

    parser.add_argument(
        "--output",
        default="fake_logs.jsonl",
        help="Output file path. Default: fake_logs.jsonl",
    )

    parser.add_argument(
        "--rows",
        type=int,
        default=1_000_000,
        help="Number of log rows to generate. Default: 1,000,000",
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=10_000,
        help="Number of rows written per batch. Default: 10,000",
    )

    parser.add_argument(
        "--days-back",
        type=int,
        default=30,
        help="Generate logs from now back N days. Default: 30",
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional random seed for reproducible logs.",
    )

    args = parser.parse_args()

    generate_logs(
        output_file=Path(args.output),
        rows=args.rows,
        batch_size=args.batch_size,
        days_back=args.days_back,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()