from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from src.app.shared import (
    DEFAULT_CONFIG,
    HISTORY_PATH,
    MODE_LABELS,
    RuntimeConfig,
    STATE_PATH,
    StateSnapshot,
    load_config,
    load_history,
    load_state,
    save_config,
    write_json,
)

Mode = Literal["mode_a", "mode_b", "mode_c"]


class ConfigUpdate(BaseModel):
    mode: Mode | None = None
    load_profile: str | None = None
    producer_rate: int | None = Field(default=None, ge=0, le=5000)
    processing_cost_ms: int | None = Field(default=None, ge=1, le=1000)
    static_rate: int | None = Field(default=None, ge=1, le=5000)
    adaptive_rate: float | None = Field(default=None, ge=1, le=5000)
    adaptive_min_rate: float | None = Field(default=None, ge=1, le=5000)
    adaptive_max_rate: float | None = Field(default=None, ge=1, le=5000)


app = FastAPI(
  title="SSC0904 - Pipeline Distribuido G09",
  version="1.0.0",
    description=(
        "API simples para controle e observacao do pipeline com Kafka. "
        "A documentacao Swagger fica disponivel em /docs."
    ),
)

PROMETHEUS_PUBLIC_PORT = os.getenv("PUBLIC_PROMETHEUS_PORT", "9090")
GRAFANA_PUBLIC_PORT = os.getenv("PUBLIC_GRAFANA_PORT", "3000")


@app.get("/", response_class=HTMLResponse, summary="Dashboard simples")
def dashboard() -> str:
    html = """
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>G09 - Pipeline distribuido</title>
  <style>
    :root{color-scheme:light;background:#f6f4ee;color:#1b1a17;font-family:Georgia,serif}
    body{margin:0;background:linear-gradient(180deg,#f7f3e8,#ebe4d1);min-height:100vh}
    header{padding:28px 24px 10px}
    h1{margin:0;font-size:2rem}
    p{line-height:1.5}
    main{padding:0 24px 24px;display:grid;gap:16px}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}
    .card{background:#fffaf0;border:1px solid #d7cdb7;border-radius:18px;padding:18px;box-shadow:0 10px 30px rgba(120,94,38,.08)}
    .value{font-size:2rem;font-weight:700;color:#8b4513}
    button{border:0;border-radius:999px;padding:10px 16px;background:#245c4a;color:#fff;cursor:pointer;margin-right:8px;margin-bottom:8px}
    pre{white-space:pre-wrap;background:#2f2a22;color:#f8f4ea;padding:14px;border-radius:14px;overflow:auto}
    a{color:#245c4a}
  </style>
</head>
<body>
  <header>
    <h1>Controle de fluxo em pipeline distribuido</h1>
    <p>Swagger: <a href="/docs">/docs</a> | Prometheus: <a id="prometheus-link" href="#">:__PROMETHEUS_PORT__</a> | Grafana: <a id="grafana-link" href="#">:__GRAFANA_PORT__</a></p>
  </header>
  <main>
    <section class="grid">
      <div class="card"><strong>Modo atual</strong><div id="mode" class="value">-</div></div>
      <div class="card"><strong>Throughput</strong><div id="throughput" class="value">-</div></div>
      <div class="card"><strong>Latencia p95</strong><div id="latency" class="value">-</div></div>
      <div class="card"><strong>Backlog</strong><div id="backlog" class="value">-</div></div>
    </section>
    <section class="card">
      <strong>Trocar modo</strong>
      <div style="margin-top:12px">
        <button onclick="setMode('mode_a')">Modo A</button>
        <button onclick="setMode('mode_b')">Modo B</button>
        <button onclick="setMode('mode_c')">Modo C</button>
        <button onclick="resetPipeline()">Resetar</button>
      </div>
    </section>
    <section class="card">
      <strong>Estado atual</strong>
      <pre id="state">carregando...</pre>
    </section>
  </main>
  <script>
    document.getElementById('prometheus-link').href = `http://${window.location.hostname}:__PROMETHEUS_PORT__`;
    document.getElementById('grafana-link').href = `http://${window.location.hostname}:__GRAFANA_PORT__`;
    async function refresh() {
      const response = await fetch('/api/status');
      const data = await response.json();
      document.getElementById('mode').textContent = data.config.mode;
      document.getElementById('throughput').textContent = `${data.state.throughput_messages_s.toFixed(2)} msg/s`;
      document.getElementById('latency').textContent = `${data.state.latency_p95_ms.toFixed(2)} ms`;
      document.getElementById('backlog').textContent = `${data.state.backlog}`;
      document.getElementById('state').textContent = JSON.stringify(data, null, 2);
    }
    async function setMode(mode) {
      await fetch('/api/config', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({mode})});
      refresh();
    }
    async function resetPipeline() {
      await fetch('/api/reset', {method: 'POST'});
      refresh();
    }
    refresh();
    setInterval(refresh, 3000);
  </script>
</body>
</html>
"""
    return (
        html.replace("__PROMETHEUS_PORT__", PROMETHEUS_PUBLIC_PORT)
        .replace("__GRAFANA_PORT__", GRAFANA_PUBLIC_PORT)
    )


@app.get("/health", summary="Healthcheck")
def health() -> dict[str, str]:
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/config", response_model=RuntimeConfig, summary="Ler configuracao do pipeline")
def get_config() -> RuntimeConfig:
    return load_config()


@app.post("/api/config", response_model=RuntimeConfig, summary="Atualizar configuracao do pipeline")
def update_config(payload: ConfigUpdate) -> RuntimeConfig:
    current = load_config().model_dump()
    updates = payload.model_dump(exclude_none=True)
    current.update(updates)
    config = RuntimeConfig(**current)
    save_config(config)
    return config


@app.post("/api/reset", response_model=RuntimeConfig, summary="Resetar o pipeline")
def reset_pipeline() -> RuntimeConfig:
    current = load_config()
    payload = dict(DEFAULT_CONFIG)
    payload["reset_token"] = current.reset_token + 1
    config = RuntimeConfig(**payload)
    save_config(config)
    write_json(HISTORY_PATH, [])
    write_json(STATE_PATH, StateSnapshot().model_dump())
    return config


@app.get("/api/status", summary="Estado consolidado do pipeline")
def get_status() -> dict[str, object]:
    config = load_config()
    state = load_state()
    return {
        "config": config,
        "state": state,
        "mode_description": MODE_LABELS[config.mode],
    }


@app.get("/api/history", summary="Historico recente de snapshots")
def get_history(limit: int = 30) -> list[dict[str, object]]:
    return load_history(limit=limit)


@app.get("/metrics", summary="Metricas Prometheus")
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
