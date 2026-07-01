# SSC0904 - Checkpoint 4: Relatorio Final

Grupo 09  
SSC0904 - Sistemas Distribuidos  
Instituto de Ciencias Matematicas e de Computacao - ICMC/USP

## Resumo

Este relatorio final consolida o estudo comparativo entre descoberta centralizada e descoberta com cache local em sistemas distribuidos. A estrategia centralizada consulta o registro de servicos a cada requisicao. A estrategia com cache local reutiliza endpoints previamente descobertos para reduzir latencia e preservar throughput, mas pode introduzir inconsistencia temporaria em cenarios com churn.

O repositorio foi ajustado para nao manter resultados antigos versionados. A execucao na VM deve produzir um CSV bruto real com as medicoes do experimento. Em seguida, um script unificado limpa artefatos processados anteriores, valida o CSV, consolida metricas, gera tabelas por metrica e gera tabelas/graficos por requisito RQ1-RQ4.

## Questoes de Pesquisa

- RQ1: O uso de cache local reduz a latencia p95 em comparacao com a descoberta centralizada?
- RQ2: O cache local aumenta ou preserva o throughput do sistema?
- RQ3: Em cenarios com churn, o cache local aumenta a taxa de endpoints invalidos?
- RQ4: O ganho de desempenho do cache compensa o risco de inconsistencia temporaria?

## Metodologia

A metodologia compara duas estrategias (`cached` e `centralized`) em tres cenarios:

- `baseline_estavel`: ambiente estavel, sem churn relevante.
- `churn_moderado`: rotatividade moderada de endpoints.
- `churn_alto`: rotatividade alta de endpoints.

As metricas coletadas sao:

- latencia media;
- latencia p95;
- throughput;
- taxa de endpoint invalido.

Para cada combinacao de cenario e estrategia, o CSV bruto deve conter uma ou mais repeticoes independentes. A analise calcula media, desvio-padrao e IC95, e separa os resultados em tabelas por metrica e por RQ.

## Execucao

Comandos principais depois de coletar o CSV real:

```bash
make discovery-clean
make discovery-analysis
make validate
```

Entrada padrao:

```bash
data/raw/discovery_experiment_runs.csv
```

Para analisar outro CSV:

```bash
DISCOVERY_INPUT=/caminho/para/discovery_experiment_runs.csv make discovery-analysis
```

## Artefatos Gerados

A entrada bruta do experimento e:

- `data/raw/discovery_experiment_runs.csv`;

Apos a analise, os arquivos sao gerados em:

- `data/processed/discovery_summary.json`;
- `data/processed/discovery_metrics/`;
- `data/processed/discovery_rqs/`;
- `results/discovery/metrics/`;
- `results/discovery/rqs/`;
- `docs/checkpoint4/generated/`.

## Leitura Esperada Dos Resultados

- RQ1 deve ser respondida pelo grafico/tabela de latencia p95: cache local e esperado como menor p95 que centralizado.
- RQ2 deve ser respondida pelo grafico/tabela de throughput: cache local deve preservar ou aumentar vazao.
- RQ3 deve ser respondida pela taxa de endpoint invalido: em churn, cache local pode aumentar endpoints invalidos.
- RQ4 deve ser respondida pelo grafico de trade-off: ganho de p95/throughput contra aumento de endpoint invalido.

## Ameacas A Validade

Resultados dependem da VM, da configuracao dos servicos, da carga aplicada, do numero de repeticoes e da parametrizacao do churn. Por isso, os artefatos finais devem sempre registrar como o CSV bruto foi coletado. Para conclusoes mais robustas, recomenda-se executar pelo menos cinco repeticoes por cenario/estrategia.

## Conclusao

A entrega final esta organizada para que os resultados sejam sempre coletados na VM e analisados a partir de um CSV bruto explicito, evitando mistura com resultados antigos. O fluxo unificado gera automaticamente os elementos tabulares e graficos necessarios para responder RQ1, RQ2, RQ3 e RQ4.