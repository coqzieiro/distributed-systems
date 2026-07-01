VENV_DIR ?= .venv
VENV_PYTHON := $(VENV_DIR)/bin/python
PYTHON ?= $(if $(wildcard $(VENV_PYTHON)),$(VENV_PYTHON),python3)
COMPOSE ?= docker compose
TMP_DATA_ROOT ?= /tmp/$(USER)/projeto-ssc0904-grupo09/data
RAW_DATA_DIR ?= $(TMP_DATA_ROOT)/raw
PROCESSED_DATA_DIR ?= $(TMP_DATA_ROOT)/processed
TMP_OBSERVABILITY_ROOT ?= /tmp/$(USER)/projeto-ssc0904-grupo09/observability
PROMETHEUS_CONFIG_FILE ?= $(TMP_OBSERVABILITY_ROOT)/prometheus/prometheus.yml
GRAFANA_PROVISIONING_DIR ?= $(TMP_OBSERVABILITY_ROOT)/grafana/provisioning
GRAFANA_DASHBOARDS_DIR ?= $(TMP_OBSERVABILITY_ROOT)/grafana/dashboards
COMPOSE_ENV = RAW_DATA_DIR="$(RAW_DATA_DIR)" PROCESSED_DATA_DIR="$(PROCESSED_DATA_DIR)" PROMETHEUS_CONFIG_FILE="$(PROMETHEUS_CONFIG_FILE)" GRAFANA_PROVISIONING_DIR="$(GRAFANA_PROVISIONING_DIR)" GRAFANA_DASHBOARDS_DIR="$(GRAFANA_DASHBOARDS_DIR)"

# --- Modo local (infra no Docker, Python no host) ---
LOCAL_COMPOSE_CMD = $(COMPOSE) -f docker-compose.yml -f docker-compose.local.yml
LOCAL_RUNTIME_DIR ?= data/runtime
LOCAL_LOGS_DIR    ?= logs/local
LOCAL_PIDS_DIR    ?= .pids
LOCAL_ENV = \
	KAFKA_BOOTSTRAP_SERVERS=localhost:9092 \
	INFLUX_URL=http://localhost:8086 \
	INFLUX_TOKEN=g09-token \
	INFLUX_ORG=g09 \
	INFLUX_BUCKET=pipeline \
	PIPELINE_RUNTIME_DIR=$(LOCAL_RUNTIME_DIR) \
	PUBLIC_PROMETHEUS_PORT=9090 \
	PUBLIC_GRAFANA_PORT=3000

DISCOVERY_INPUT ?= data/raw/discovery_experiment_runs.csv
DISCOVERY_OUTPUT_ROOT ?= .
PIPELINE_BASE_URL ?= http://localhost:5051
PIPELINE_WARMUP ?= 30
PIPELINE_DURATION ?= 300
PIPELINE_REPETITIONS ?= 5
PIPELINE_RAW_OUTPUT ?= data/raw/pipeline_experiment_rq3.csv
PIPELINE_SUMMARY_OUTPUT ?= data/processed/pipeline_summary_rq3.json
PIPELINE_PLOTS_DIR ?= results/plots_rq3
PIPELINE_RQ_OUTPUT_DIR ?= results/pipeline_rqs

DISCOVERY_SCRIPT ?= scripts/run_service_discovery_analysis.py
PIPELINE_EXPERIMENT_SCRIPT ?= experiments/run_pipeline_experiment.py
PIPELINE_SUMMARY_SCRIPT ?= scripts/summarize_pipeline_results.py
PIPELINE_PLOTS_SCRIPT ?= scripts/generate_pipeline_plots.py
PIPELINE_RQ_SCRIPT ?= scripts/generate_pipeline_rq_artifacts.py

.DEFAULT_GOAL := help

.PHONY: \
	help \
	venv install-deps preflight-python-deps \
	prepare-host-dirs \
	start stop restart reset logs \
	start-infra-local start-local stop-local logs-local \
	run-api run-producer run-consumer \
	pipeline-run pipeline-summarize pipeline-plots pipeline-rqs pipeline-analysis pipeline-all \
	discovery-analysis discovery-clean \
	validate \
	up down rebuild analysis

help:
	@echo "Fluxo recomendado (pipeline):"
	@echo "  1) make start"
	@echo "  2) make pipeline-analysis"
	@echo "  3) make stop"
	@echo ""
	@echo "Alvos principais:"
	@echo "  start               Sobe os containers"
	@echo "  stop                Derruba os containers"
	@echo "  reset               Derruba com volumes"
	@echo "  Diretorios Docker:  RAW_DATA_DIR=$(RAW_DATA_DIR)"
	@echo "                      PROCESSED_DATA_DIR=$(PROCESSED_DATA_DIR)"
	@echo "                      PROMETHEUS_CONFIG_FILE=$(PROMETHEUS_CONFIG_FILE)"
	@echo "                      GRAFANA_PROVISIONING_DIR=$(GRAFANA_PROVISIONING_DIR)"
	@echo "                      GRAFANA_DASHBOARDS_DIR=$(GRAFANA_DASHBOARDS_DIR)"
	@echo "  logs                Logs de api/producer/consumer"
	@echo "  pipeline-run        Executa experimento do RQ3 (gera CSV bruto)"
	@echo "  pipeline-summarize  Gera resumo JSON do RQ3"
	@echo "  pipeline-plots      Gera graficos do RQ3"
	@echo "  pipeline-rqs        Gera tabelas/graficos RQ1-RQ4 por modo (A/B/C)"
	@echo "  pipeline-analysis   Executa run + summarize + plots + rqs"
	@echo "  pipeline-all        Sobe stack e roda pipeline-analysis"
	@echo "  start-local         Sobe apenas Kafka+InfluxDB (Docker) e roda Python no host"
	@echo "  stop-local          Para servicos Python locais e derruba infra Docker"
	@echo "  logs-local          Exibe logs dos servicos Python locais"
	@echo "  venv                Cria ambiente virtual local (.venv)"
	@echo "  install-deps        Instala dependencias Python do projeto"
	@echo "  preflight-python-deps Valida modulos Python obrigatorios"
	@echo "  discovery-analysis  Analise RQ1-RQ4 por CSV de discovery"
	@echo "  discovery-clean     Limpa artefatos de discovery"
	@echo "  validate            Validacao rapida de scripts"

venv:
	@if [ -x "$(VENV_PYTHON)" ]; then \
		echo "Ambiente virtual ja existe em $(VENV_DIR)."; \
	else \
		echo "Criando ambiente virtual em $(VENV_DIR)..."; \
		echo "Este passo pode levar alguns minutos na primeira execucao."; \
		python3 -m venv "$(VENV_DIR)"; \
		echo "Ambiente virtual criado em $(VENV_DIR)."; \
	fi

install-deps: venv
	$(VENV_PYTHON) -m pip install --upgrade pip
	$(VENV_PYTHON) -m pip install -r requirements.txt

preflight-python-deps:
	@$(PYTHON) -c "import scipy, matplotlib" || ( \
		echo "Dependencias Python ausentes no ambiente atual ($(PYTHON))."; \
		echo "Execute: make install-deps"; \
		exit 1 \
	)

start:
	@$(MAKE) prepare-host-dirs
	$(COMPOSE_ENV) $(COMPOSE) up -d --no-recreate

rebuild:
	@$(MAKE) prepare-host-dirs
	$(COMPOSE_ENV) $(COMPOSE) up -d --build

prepare-host-dirs:
	mkdir -p "$(RAW_DATA_DIR)" "$(PROCESSED_DATA_DIR)"
	mkdir -p "$(dir $(PROMETHEUS_CONFIG_FILE))"
	cp -f observability/prometheus/prometheus.yml "$(PROMETHEUS_CONFIG_FILE)"
	mkdir -p "$(GRAFANA_PROVISIONING_DIR)" "$(GRAFANA_DASHBOARDS_DIR)"
	cp -a observability/grafana/provisioning/. "$(GRAFANA_PROVISIONING_DIR)/"
	cp -a observability/grafana/dashboards/. "$(GRAFANA_DASHBOARDS_DIR)/"

stop:
	$(COMPOSE_ENV) $(COMPOSE) down

restart: stop start

reset:
	$(COMPOSE_ENV) $(COMPOSE) down -v

logs:
	$(COMPOSE_ENV) $(COMPOSE) logs -f api producer consumer

discovery-analysis:
	$(PYTHON) $(DISCOVERY_SCRIPT) --clean --raw-input "$(DISCOVERY_INPUT)" --output-root "$(DISCOVERY_OUTPUT_ROOT)"

discovery-clean:
	$(PYTHON) $(DISCOVERY_SCRIPT) --clean --clean-raw --clean-only --raw-input "$(DISCOVERY_INPUT)" --output-root "$(DISCOVERY_OUTPUT_ROOT)"

pipeline-run:
	$(PYTHON) $(PIPELINE_EXPERIMENT_SCRIPT) --base-url "$(PIPELINE_BASE_URL)" --warmup "$(PIPELINE_WARMUP)" --duration "$(PIPELINE_DURATION)" --repetitions "$(PIPELINE_REPETITIONS)" --output "$(PIPELINE_RAW_OUTPUT)"

pipeline-summarize: preflight-python-deps
	$(PYTHON) $(PIPELINE_SUMMARY_SCRIPT) --input "$(PIPELINE_RAW_OUTPUT)" --output "$(PIPELINE_SUMMARY_OUTPUT)"

pipeline-plots:
	$(PYTHON) $(PIPELINE_PLOTS_SCRIPT) --input "$(PIPELINE_SUMMARY_OUTPUT)" --output-dir "$(PIPELINE_PLOTS_DIR)"

pipeline-rqs: pipeline-summarize
	$(PYTHON) $(PIPELINE_RQ_SCRIPT) --input "$(PIPELINE_SUMMARY_OUTPUT)" --output-dir "$(PIPELINE_RQ_OUTPUT_DIR)"

pipeline-analysis: preflight-python-deps pipeline-run pipeline-summarize pipeline-plots pipeline-rqs

pipeline-all: start pipeline-analysis

# ---------------------------------------------------------------------------
# Modo local: Kafka + InfluxDB sobem no Docker; API/producer/consumer no host
# ---------------------------------------------------------------------------

start-infra-local: ## Sobe apenas Kafka e InfluxDB no Docker com portas expostas
	$(LOCAL_COMPOSE_CMD) up -d kafka influxdb
	@echo "Aguardando Kafka inicializar (12s)..."
	@sleep 12

run-api: ## Roda a API FastAPI no host (requer infra ativa via start-infra-local)
	@mkdir -p "$(LOCAL_RUNTIME_DIR)"
	$(LOCAL_ENV) $(PYTHON) -m uvicorn src.app.main:app --host 0.0.0.0 --port 5051

run-producer: ## Roda o producer no host
	@mkdir -p "$(LOCAL_RUNTIME_DIR)"
	$(LOCAL_ENV) $(PYTHON) -m src.app.producer

run-consumer: ## Roda o consumer no host
	@mkdir -p "$(LOCAL_RUNTIME_DIR)"
	$(LOCAL_ENV) $(PYTHON) -m src.app.consumer

start-local: start-infra-local ## Sobe infra Docker + inicia API/producer/consumer em background
	@mkdir -p "$(LOCAL_RUNTIME_DIR)" "$(LOCAL_LOGS_DIR)" "$(LOCAL_PIDS_DIR)"
	@$(LOCAL_ENV) nohup $(PYTHON) -m uvicorn src.app.main:app \
		--host 0.0.0.0 --port 5051 \
		> "$(LOCAL_LOGS_DIR)/api.log" 2>&1 & echo $$! > "$(LOCAL_PIDS_DIR)/api.pid"
	@echo "API iniciada (pid=$$(cat $(LOCAL_PIDS_DIR)/api.pid)) — aguardando 3s..."
	@sleep 3
	@$(LOCAL_ENV) nohup $(PYTHON) -m src.app.producer \
		> "$(LOCAL_LOGS_DIR)/producer.log" 2>&1 & echo $$! > "$(LOCAL_PIDS_DIR)/producer.pid"
	@$(LOCAL_ENV) nohup $(PYTHON) -m src.app.consumer \
		> "$(LOCAL_LOGS_DIR)/consumer.log" 2>&1 & echo $$! > "$(LOCAL_PIDS_DIR)/consumer.pid"
	@echo "Servicos locais rodando:"
	@echo "  API      -> http://localhost:5051/docs  (log: $(LOCAL_LOGS_DIR)/api.log)"
	@echo "  Producer -> log: $(LOCAL_LOGS_DIR)/producer.log"
	@echo "  Consumer -> log: $(LOCAL_LOGS_DIR)/consumer.log"
	@echo "Para parar: make stop-local"

stop-local: ## Para os processos Python locais e derruba Kafka/InfluxDB
	@for svc in api producer consumer; do \
		pid_file="$(LOCAL_PIDS_DIR)/$$svc.pid"; \
		if [ -f "$$pid_file" ]; then \
			pid=$$(cat "$$pid_file"); \
			kill "$$pid" 2>/dev/null && echo "Parado $$svc (pid=$$pid)" || echo "$$svc ja encerrado"; \
			rm -f "$$pid_file"; \
		fi; \
	done
	$(LOCAL_COMPOSE_CMD) down

logs-local: ## Exibe logs em tempo real dos servicos Python locais
	tail -f "$(LOCAL_LOGS_DIR)/api.log" "$(LOCAL_LOGS_DIR)/producer.log" "$(LOCAL_LOGS_DIR)/consumer.log"

# Compatibilidade com comandos antigos
up: start
down: stop
analysis: discovery-analysis

validate:
	$(PYTHON) -m py_compile src/app/*.py experiments/*.py scripts/*.py
	rm -rf /tmp/service-discovery-validation
	mkdir -p /tmp/service-discovery-validation/data/raw
	printf 'repetition,scenario,strategy,requests,latency_mean_ms,latency_p95_ms,throughput_req_s,invalid_endpoint_rate,invalid_endpoint_count\n1,baseline_estavel,cached,600,1.8,3.4,155,0,0\n1,baseline_estavel,centralized,600,9.9,11.8,151,0,0\n1,churn_moderado,cached,800,2.0,3.9,198,0.012,10\n1,churn_moderado,centralized,800,10.2,12.1,197,0,0\n1,churn_alto,cached,1000,2.4,4.6,214,0.052,52\n1,churn_alto,centralized,1000,10.6,12.8,197,0,0\n' > /tmp/service-discovery-validation/data/raw/discovery_experiment_runs.csv
	$(PYTHON) $(DISCOVERY_SCRIPT) --clean --raw-input data/raw/discovery_experiment_runs.csv --output-root /tmp/service-discovery-validation
