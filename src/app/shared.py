from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

Mode = Literal["mode_a", "mode_b", "mode_c"]

DATA_DIR = Path(os.getenv("PIPELINE_RUNTIME_DIR", "data/runtime"))
CONFIG_PATH = DATA_DIR / "config.json"
STATE_PATH = DATA_DIR / "state.json"
HISTORY_PATH = DATA_DIR / "history.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "mode": "mode_a",
    "load_profile": "moderada",
    "producer_rate": 25,
    "processing_cost_ms": 20,
    "static_rate": 12,
    "adaptive_rate": 20.0,
    "adaptive_min_rate": 5.0,
    "adaptive_max_rate": 30.0,
    "adaptive_threshold": 0.6,
    "adaptive_gain": 0.1,
    "alpha": 0.4,
    "beta": 0.4,
    "gamma": 0.2,
    "topic": "pipeline-events",
    "reset_token": 0,
}

MODE_LABELS = {
    "mode_a": "Modo A - sem controle de fluxo",
    "mode_b": "Modo B - controle estatico",
    "mode_c": "Modo C - controle adaptativo",
}


class RuntimeConfig(BaseModel):
    mode: Mode = "mode_a"
    load_profile: str = "moderada"
    producer_rate: int = Field(default=25, ge=0, le=5000)
    processing_cost_ms: int = Field(default=20, ge=1, le=1000)
    static_rate: int = Field(default=12, ge=1, le=5000)
    adaptive_rate: float = Field(default=20.0, ge=1, le=5000)
    adaptive_min_rate: float = Field(default=5.0, ge=1, le=5000)
    adaptive_max_rate: float = Field(default=30.0, ge=1, le=5000)
    adaptive_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    adaptive_gain: float = Field(default=0.1, ge=0.01, le=1.0)
    alpha: float = Field(default=0.4, ge=0.0, le=1.0)
    beta: float = Field(default=0.4, ge=0.0, le=1.0)
    gamma: float = Field(default=0.2, ge=0.0, le=1.0)
    topic: str = "pipeline-events"
    reset_token: int = 0


class StateSnapshot(BaseModel):
    mode: str = MODE_LABELS["mode_a"]
    load_profile: str = "moderada"
    producer_rate: int = 25
    throughput_messages_s: float = 0.0
    latency_p95_ms: float = 0.0
    backlog: int = 0
    backlog_sigma: float = 0.0
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    produced_total_estimate: int = 0
    processed_total: int = 0
    adaptive_rate: float = 20.0
    control_score: float = 0.0
    updated_at: str = ""


def ensure_runtime_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: Any) -> None:
    ensure_runtime_dir()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path, default: Any) -> Any:
    ensure_runtime_dir()
    if not path.exists():
        write_json(path, default)
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        write_json(path, default)
        return default


def load_config() -> RuntimeConfig:
    return RuntimeConfig(**read_json(CONFIG_PATH, DEFAULT_CONFIG))


def save_config(config: RuntimeConfig) -> None:
    write_json(CONFIG_PATH, config.model_dump())


def load_state() -> StateSnapshot:
    return StateSnapshot(**read_json(STATE_PATH, StateSnapshot().model_dump()))


def save_state(snapshot: StateSnapshot) -> None:
    write_json(STATE_PATH, snapshot.model_dump())


def load_history(limit: int = 30) -> list[dict[str, Any]]:
    history = read_json(HISTORY_PATH, [])
    if not isinstance(history, list):
        return []
    return history[-limit:]


def append_history(snapshot: StateSnapshot, limit: int = 500) -> None:
    history = load_history(limit=limit)
    history.append(snapshot.model_dump())
    write_json(HISTORY_PATH, history[-limit:])
