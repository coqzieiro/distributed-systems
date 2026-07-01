from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


LOAD_PROFILES = [
    ("baixa", 20),
    ("moderada", 32),
    ("alta", 44),
    ("sobrecarga", 60),
]
MODES = ["mode_a", "mode_b", "mode_c"]


def format_seconds(total_seconds: int) -> str:
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def request(base_url: str, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = Request(base_url.rstrip("/") + path, data=data, method=method)
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    with urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_timestamp(raw_timestamp: str) -> datetime:
    return datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))


def mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def backlog_sigma(values: list[float]) -> float:
    return statistics.pstdev(values) if len(values) > 1 else 0.0


def run_experiment(base_url: str, warmup_s: int, duration_s: int, repetitions: int, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    total_scenarios = repetitions * len(LOAD_PROFILES) * len(MODES)
    estimated_total_time = total_scenarios * (warmup_s + duration_s)
    scenario_index = 0

    print(
        (
            f"Iniciando experimento com {total_scenarios} cenarios "
            f"({repetitions} repeticoes x {len(LOAD_PROFILES)} cargas x {len(MODES)} modos). "
            f"Tempo estimado (warmup + coleta): {format_seconds(estimated_total_time)}."
        ),
        flush=True,
    )

    for repetition in range(1, repetitions + 1):
        for load_profile, producer_rate in LOAD_PROFILES:
            for mode in MODES:
                scenario_index += 1
                remaining_scenarios = total_scenarios - scenario_index
                estimated_remaining_time = remaining_scenarios * duration_s
                print(
                    (
                        f"[{scenario_index}/{total_scenarios}] "
                        f"repeticao={repetition} carga={load_profile} ({producer_rate} msg/s) modo={mode} | "
                        f"warmup={warmup_s}s coleta={duration_s}s | restante estimado: "
                        f"{format_seconds(remaining_scenarios * (warmup_s + duration_s))}"
                    ),
                    flush=True,
                )
                request(base_url, "POST", "/api/reset", {})
                request(
                    base_url,
                    "POST",
                    "/api/config",
                    {
                        "mode": mode,
                        "load_profile": load_profile,
                        "producer_rate": producer_rate,
                        "processing_cost_ms": 20,
                        "static_rate": 12,
                        "adaptive_rate": 20.0,
                        "adaptive_min_rate": 5.0,
                        "adaptive_max_rate": 30.0,
                    },
                )
                time.sleep(warmup_s)
                collection_start = datetime.now(timezone.utc)
                time.sleep(duration_s)
                snapshot = request(base_url, "GET", "/api/status")
                state = snapshot["state"]
                history = request(base_url, "GET", "/api/history?limit=100")
                second_half_start = collection_start + timedelta(seconds=duration_s / 2)
                second_half_samples = [
                    item for item in history if parse_timestamp(str(item["updated_at"])) >= second_half_start
                ]
                if not second_half_samples:
                    second_half_samples = [state]
                second_half_backlog = [float(item["backlog"]) for item in second_half_samples]
                second_half_cpu = [float(item["cpu_percent"]) for item in second_half_samples]
                second_half_memory = [float(item["memory_mb"]) for item in second_half_samples]
                print(
                    (
                        f"  -> throughput={state['throughput_messages_s']:.3f} msg/s, "
                        f"latencia_p95={state['latency_p95_ms']:.3f} ms, "
                        f"backlog={state['backlog']}, "
                        f"cpu_medio_2a_metade={mean(second_half_cpu):.3f}%"
                    ),
                    flush=True,
                )
                rows.append(
                    {
                        "repetition": repetition,
                        "mode": mode,
                        "load_profile": load_profile,
                        "producer_rate": producer_rate,
                        "throughput_messages_s": state["throughput_messages_s"],
                        "latency_p95_ms": state["latency_p95_ms"],
                        "backlog": state["backlog"],
                        "cpu_percent": state["cpu_percent"],
                        "memory_mb": state["memory_mb"],
                        "backlog_sigma": state.get("backlog_sigma", 0.0),
                        "adaptive_rate": state["adaptive_rate"],
                        "control_score": state["control_score"],
                        "backlog_sigma_second_half": backlog_sigma(second_half_backlog),
                        "cpu_mean_second_half": mean(second_half_cpu),
                        "memory_mean_second_half": mean(second_half_memory),
                        "updated_at": state["updated_at"],
                    }
                )

    with output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Executa uma bateria simples do pipeline atual.")
    parser.add_argument("--base-url", default="http://localhost:5051")
    parser.add_argument("--warmup", type=int, default=30, help="Tempo de warmup por cenario, em segundos.")
    parser.add_argument("--duration", type=int, default=300, help="Tempo de coleta por cenario, em segundos.")
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--output", default="data/raw/pipeline_experiment_rq3.csv")
    args = parser.parse_args()

    output = run_experiment(args.base_url, args.warmup, args.duration, args.repetitions, Path(args.output))
    print(f"Experimento salvo em {output}", flush=True)


if __name__ == "__main__":
    main()
