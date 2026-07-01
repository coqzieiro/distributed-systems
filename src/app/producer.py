from __future__ import annotations

import json
import os
import sys
import time
from uuid import uuid4

import six
sys.modules["kafka.vendor.six.moves"] = six.moves

from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable

from src.app.shared import load_config


def wait_producer(bootstrap_servers: str) -> KafkaProducer:
    while True:
        try:
            producer = KafkaProducer(
                bootstrap_servers=bootstrap_servers,
                value_serializer=lambda value: json.dumps(value).encode("utf-8"),
            )
            if producer.bootstrap_connected():
                return producer
        except NoBrokersAvailable:
            pass
        time.sleep(2)


def main() -> None:
    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    producer = wait_producer(bootstrap_servers)
    local_reset_token = -1
    produced_total = 0

    while True:
        config = load_config()
        if local_reset_token != config.reset_token:
            produced_total = 0
            local_reset_token = config.reset_token

        if config.producer_rate <= 0:
            time.sleep(1)
            continue

        interval = 1.0 / config.producer_rate
        payload = {
            "message_id": str(uuid4()),
            "produced_at_ns": time.time_ns(),
            "load_profile": config.load_profile,
            "producer_rate": config.producer_rate,
            "sequence": produced_total + 1,
        }
        producer.send(config.topic, payload)
        produced_total += 1
        if produced_total % 50 == 0:
            producer.flush()
        time.sleep(interval)


if __name__ == "__main__":
    main()
