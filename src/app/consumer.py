from __future__ import annotations

import math
import os
import statistics
import sys
import time
from collections import deque
from datetime import datetime, timezone

import psutil
import six
sys.modules["kafka.vendor.six.moves"] = six.moves

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from kafka import KafkaConsumer
from kafka.errors import NoBrokersAvailable
from prometheus_client import Gauge, start_http_server

from src.app.shared import MODE_LABELS, RuntimeConfig, StateSnapshot, append_history, load_config, save_state

THROUGHPUT = Gauge("pipeline_throughput_messages_s", "Throughput do consumidor em mensagens por segundo.")
LATENCY_P95 = Gauge("pipeline_latency_p95_ms", "Latencia p95 ponta a ponta em milissegundos.")
BACKLOG = Gauge("pipeline_backlog_messages", "Backlog estimado do topico Kafka.")
BACKLOG_SIGMA = Gauge("pipeline_backlog_sigma", "Desvio padrao recente do backlog.")
CPU = Gauge("pipeline_consumer_cpu_percent", "Uso de CPU do consumidor.")
MEMORY = Gauge("pipeline_consumer_memory_mb", "Uso de memoria RSS do consumidor em MB.")
ADAPTIVE_RATE = Gauge("pipeline_adaptive_rate_messages_s", "Taxa alvo atual no modo adaptativo.")
CONTROL_SCORE = Gauge("pipeline_control_score", "Score do controlador adaptativo.")

SNAPSHOT_INTERVAL_S = 5
ADAPTIVE_CONTROL_INTERVAL_S = 10


def percentile_95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def wait_consumer(topic: str) -> KafkaConsumer:
    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    while True:
        try:
            consumer = KafkaConsumer(
                topic,
                bootstrap_servers=bootstrap_servers,
                value_deserializer=lambda value: __import__("json").loads(value.decode("utf-8")),
                enable_auto_commit=False,
                auto_offset_reset="latest",
                group_id="pipeline-consumer",
                consumer_timeout_ms=1000,
            )
            return consumer
        except NoBrokersAvailable:
            time.sleep(2)


def connect_influx() -> InfluxDBClient | None:
    try:
        return InfluxDBClient(
            url=os.getenv("INFLUX_URL", "http://influxdb:8086"),
            token=os.getenv("INFLUX_TOKEN", "g09-token"),
            org=os.getenv("INFLUX_ORG", "g09"),
        )
    except Exception:
        return None


def maybe_wait(config: RuntimeConfig, current_rate: float, last_processed_at: float) -> float:
    if current_rate <= 0:
        return time.perf_counter()
    min_interval = 1.0 / current_rate
    elapsed = time.perf_counter() - last_processed_at
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)
    return time.perf_counter()


def simulate_processing(cost_ms: int) -> None:
    deadline = time.perf_counter() + (cost_ms / 1000.0)
    accumulator = 0.0
    iteration = 1
    while time.perf_counter() < deadline:
        accumulator += math.sqrt(iteration % 1000 + 1)
        iteration += 1
    if accumulator < 0:
        raise RuntimeError("unreachable")


def reset_consumer_state(consumer: KafkaConsumer) -> None:
    consumer.poll(timeout_ms=100)
    if consumer.assignment():
        consumer.seek_to_end(*list(consumer.assignment()))
        consumer.commit()


def main() -> None:
    start_http_server(8001)
    config = load_config()
    consumer = wait_consumer(config.topic)
    influx = connect_influx()
    write_api = influx.write_api(write_options=SYNCHRONOUS) if influx is not None else None
    process = psutil.Process()
    process.cpu_percent(None)

    recent_latencies: deque[tuple[float, float]] = deque()
    recent_processed_at: deque[float] = deque()
    recent_backlog: deque[tuple[float, int]] = deque()
    local_reset_token = config.reset_token
    adaptive_rate = config.adaptive_rate
    processed_total = 0
    last_processed_at = time.perf_counter()
    last_snapshot_at = 0.0
    last_adaptive_update_at = 0.0

    while True:
        config = load_config()
        if config.reset_token != local_reset_token:
            reset_consumer_state(consumer)
            recent_latencies.clear()
            recent_processed_at.clear()
            recent_backlog.clear()
            processed_total = 0
            adaptive_rate = config.adaptive_rate
            local_reset_token = config.reset_token
            last_adaptive_update_at = 0.0

        messages = consumer.poll(timeout_ms=1000, max_records=20)
        now = time.time()
        if messages:
            for records in messages.values():
                for record in records:
                    if config.mode == "mode_b":
                        last_processed_at = maybe_wait(config, float(config.static_rate), last_processed_at)
                    elif config.mode == "mode_c":
                        last_processed_at = maybe_wait(config, adaptive_rate, last_processed_at)

                    simulate_processing(config.processing_cost_ms)
                    latency_ms = (time.time_ns() - int(record.value["produced_at_ns"])) / 1_000_000
                    processed_total += 1
                    timestamp = time.time()
                    recent_latencies.append((timestamp, latency_ms))
                    recent_processed_at.append(timestamp)

            consumer.commit()

        while recent_latencies and now - recent_latencies[0][0] > 10:
            recent_latencies.popleft()
        while recent_processed_at and now - recent_processed_at[0] > 10:
            recent_processed_at.popleft()

        if now - last_snapshot_at < SNAPSHOT_INTERVAL_S:
            continue
        last_snapshot_at = now

        backlog = 0
        produced_total_estimate = 0
        for partition in consumer.assignment():
            end_offset = consumer.end_offsets([partition])[partition]
            current_offset = consumer.position(partition)
            produced_total_estimate = max(produced_total_estimate, end_offset)
            backlog += max(end_offset - current_offset, 0)
        recent_backlog.append((now, backlog))
        while recent_backlog and now - recent_backlog[0][0] > 30:
            recent_backlog.popleft()

        latencies = [item[1] for item in recent_latencies]
        throughput = len(recent_processed_at) / 10.0
        latency_p95_ms = percentile_95(latencies)
        backlog_sigma = statistics.pstdev([float(item[1]) for item in recent_backlog]) if len(recent_backlog) > 1 else 0.0
        cpu_percent = process.cpu_percent(None)
        memory_mb = process.memory_info().rss / (1024 * 1024)

        backlog_norm = min(backlog / 100.0, 1.0)
        latency_norm = min(latency_p95_ms / 500.0, 1.0)
        cpu_norm = min(cpu_percent / 100.0, 1.0)
        control_score = (
            config.alpha * backlog_norm
            + config.beta * latency_norm
            + config.gamma * cpu_norm
        )

        if config.mode == "mode_c" and (now - last_adaptive_update_at >= ADAPTIVE_CONTROL_INTERVAL_S):
            adaptive_rate = adaptive_rate * (1 - config.adaptive_gain * (control_score - config.adaptive_threshold))
            adaptive_rate = max(config.adaptive_min_rate, min(config.adaptive_max_rate, adaptive_rate))
            last_adaptive_update_at = now
        else:
            if config.mode != "mode_c":
                adaptive_rate = config.adaptive_rate

        snapshot = StateSnapshot(
            mode=MODE_LABELS[config.mode],
            load_profile=config.load_profile,
            producer_rate=config.producer_rate,
            throughput_messages_s=throughput,
            latency_p95_ms=latency_p95_ms,
            backlog=backlog,
            backlog_sigma=backlog_sigma,
            cpu_percent=cpu_percent,
            memory_mb=memory_mb,
            produced_total_estimate=produced_total_estimate,
            processed_total=processed_total,
            adaptive_rate=adaptive_rate,
            control_score=control_score,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        save_state(snapshot)
        append_history(snapshot)

        THROUGHPUT.set(throughput)
        LATENCY_P95.set(latency_p95_ms)
        BACKLOG.set(backlog)
        BACKLOG_SIGMA.set(backlog_sigma)
        CPU.set(cpu_percent)
        MEMORY.set(memory_mb)
        ADAPTIVE_RATE.set(adaptive_rate)
        CONTROL_SCORE.set(control_score)

        if write_api is not None:
            point = (
                Point("pipeline_metrics")
                .tag("mode", config.mode)
                .tag("load_profile", config.load_profile)
                .field("throughput_messages_s", throughput)
                .field("latency_p95_ms", latency_p95_ms)
                .field("backlog", backlog)
                .field("backlog_sigma", backlog_sigma)
                .field("cpu_percent", cpu_percent)
                .field("memory_mb", memory_mb)
                .field("adaptive_rate", adaptive_rate)
                .field("control_score", control_score)
            )
            try:
                write_api.write(bucket=os.getenv("INFLUX_BUCKET", "pipeline"), record=point)
            except Exception:
                pass


if __name__ == "__main__":
    main()
