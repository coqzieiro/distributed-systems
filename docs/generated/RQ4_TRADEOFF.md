# RQ4 - O ganho compensa o risco?

| scenario | p95_reduction_percent | throughput_delta_percent | invalid_delta_percentage_points | answer | note |
| --- | --- | --- | --- | --- | --- |
| baseline_estavel | 73.1443 | 2.4054 | 0.0 | Sim | Ganho sem inconsistencia observada. |
| churn_moderado | 73.116 | 0.2612 | 1.5 | Parcialmente | Compensa se a aplicacao tolerar inconsistencia baixa. |
| churn_alto | 73.2014 | 6.9635 | 6.02 | Parcialmente | Exige mitigacao por TTL menor, invalidacao ativa ou health check. |
