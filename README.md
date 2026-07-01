# SSC0904 - Grupo 09

Projeto final para comparar duas estrategias de descoberta de servicos em sistemas distribuidos:

- `centralized`: cada requisicao consulta o registro central.
- `cached`: o cliente reutiliza endpoints armazenados em cache local.

O objetivo da entrega final e organizar a coleta real e gerar artefatos para responder diretamente as quatro questoes de pesquisa:

- RQ1: O uso de cache local reduz a latencia p95 em comparacao com a descoberta centralizada?
- RQ2: O cache local aumenta ou preserva o throughput do sistema?
- RQ3: Em cenarios com churn, o cache local aumenta a taxa de endpoints invalidos?
- RQ4: O ganho de desempenho do cache compensa o risco de inconsistencia temporaria?

## Como Rodar Na VM

### Pipeline (modos A, B e C com CSV automatico)

Para executar uma analise completa do pipeline (modos `mode_a`, `mode_b` e `mode_c`) e sempre gerar o CSV bruto novamente a cada rodada:

```bash
make pipeline-analysis
```

Esse comando:

- executa `experiments/run_pipeline_experiment.py` nos tres modos;
- executa as quatro cargas fixas por modo: `baixa` (20 msg/s), `moderada` (32 msg/s), `alta` (44 msg/s) e `sobrecarga` (60 msg/s);
- aplica warmup de 30s por cenario (sem coleta) e coleta de 300s por cenario;
- gera o CSV bruto em `data/raw/pipeline_experiment_rq3.csv`;
- gera resumo em `data/processed/pipeline_summary_rq3.json`;
- gera graficos em `results/plots_rq3/`.

Parametros uteis:

```bash
PIPELINE_WARMUP=30 PIPELINE_DURATION=300 PIPELINE_REPETITIONS=5 make pipeline-analysis
```

- `PIPELINE_WARMUP`: tempo de warmup por cenario (segundos).
- `PIPELINE_DURATION`: tempo de observacao por cenario (segundos).
- `PIPELINE_REPETITIONS`: repeticoes por carga/modo.
- `PIPELINE_BASE_URL`: endpoint da API (padrao: `http://localhost:5051`).

O script de analise nao sobe Docker, nao consulta a API e nao simula dados. Ele apenas consolida um CSV bruto real coletado na VM. Antes da analise, rode o experimento real e salve as medicoes em `data/raw/discovery_experiment_runs.csv`.

Formato minimo do CSV:

```csv
repetition,scenario,strategy,requests,latency_mean_ms,latency_p95_ms,throughput_req_s,invalid_endpoint_rate,invalid_endpoint_count
1,baseline_estavel,cached,600,1.89,3.66,154.86,0.0000,0
```

Valores aceitos:

- `scenario`: `baseline_estavel`, `churn_moderado`, `churn_alto`.
- `strategy`: `cached`, `centralized`.
- Deve existir pelo menos uma linha para cada combinacao de cenario e estrategia.

Com o CSV real pronto, rode:

```bash
make discovery-analysis
```

Para usar outro arquivo de entrada:

```bash
DISCOVERY_INPUT=/caminho/para/discovery_experiment_runs.csv make discovery-analysis
```

Ou diretamente pelo Python:

```bash
python3 scripts/run_service_discovery_analysis.py --clean --raw-input data/raw/discovery_experiment_runs.csv
```

Para remover resultados processados, graficos e o CSV bruto antes de uma nova coleta:

```bash
make discovery-clean
```

## Saidas Geradas

Os resultados nao ficam versionados por padrao. A entrada esperada e:

- CSV bruto real: `data/raw/discovery_experiment_runs.csv`

Ao rodar a analise, o script cria:

- Resumo JSON completo: `data/processed/discovery_summary.json`
- Tabelas por metrica: `data/processed/discovery_metrics/`
- Tabelas por requisito/RQ: `data/processed/discovery_rqs/`
- Graficos por metrica: `results/discovery/metrics/`
- Graficos por requisito/RQ: `results/discovery/rqs/`
- Markdown gerado para o relatorio: `docs/checkpoint4/generated/`

## Organizacao Dos Scripts

- [scripts/run_service_discovery_analysis.py](scripts/run_service_discovery_analysis.py): script unificado para limpar resultados, validar CSV real, consolidar metricas, gerar tabelas e gerar graficos.
- [Makefile](Makefile): atalhos `discovery-analysis`, `discovery-clean`, `analysis` e `validate`.

## Validacao

```bash
make validate
```

Esse comando valida sintaxe Python e executa a analise com um fixture minimo em `/tmp/service-discovery-validation`, sem deixar resultados no repositorio.