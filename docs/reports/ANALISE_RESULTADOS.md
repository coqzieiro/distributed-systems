# Análise de Resultados — Checkpoint 4
**SSC0904 · Grupo 09 · Controle de Fluxo em Pipeline Distribuído**

> Dados reais coletados em VM (tau16-vm1/vm2).  
> 60 cenários · 5 repetições × 4 cargas × 3 modos · warmup 30 s · coleta 300 s/cenário.

---

## 1. Resultados Consolidados

| Carga | Modo | Throughput (msg/s) | Latência p95 (ms) | Backlog (msg) | CPU 2ª metade (%) |
|-------|------|--------------------|-------------------|---------------|-------------------|
| Baixa — 20 msg/s | **mode_a** | **19,54** | **26,5** | **0,0** | 48,2 |
| Baixa — 20 msg/s | mode_b | 14,00 | 125.648 | 2.445 | 25,0 |
| Baixa — 20 msg/s | mode_c | 19,52 | 26,6 | 0,0 | 48,9 |
| Moderada — 32 msg/s | **mode_a** | **31,16** | **24,7** | **0,0** | 71,9 |
| Moderada — 32 msg/s | mode_b | 13,64 | 199.233 | 6.104 | 24,9 |
| Moderada — 32 msg/s | mode_c | 7,68 | 207.341 | 6.354 | 15,4 |
| Alta — 44 msg/s | **mode_a** | **42,52** | **33,1** | **0,4** | 94,8 |
| Alta — 44 msg/s | mode_b | 14,00 | 234.326 | 9.743 | 24,2 |
| Alta — 44 msg/s | mode_c | 7,60 | 241.106 | 10.042 | 15,3 |
| Sobrecarga — 60 msg/s | **mode_a** | **51,70** | 45.476 | 2.604 | 98,8 |
| Sobrecarga — 60 msg/s | mode_b | 14,00 | 257.253 | 14.402 | 24,6 |
| Sobrecarga — 60 msg/s | mode_c | 7,58 | 261.761 | 14.600 | 15,1 |

### Score de Tradeoff Normalizado (0–1, maior = melhor)

| Carga | mode_a | mode_b | mode_c | Vencedor |
|-------|--------|--------|--------|----------|
| Baixa | **0,758** | 0,250 | 0,749 | mode_a |
| Moderada | **0,750** | 0,291 | 0,250 | mode_a |
| Alta | **0,750** | 0,282 | 0,250 | mode_a |
| Sobrecarga | **0,750** | 0,267 | 0,250 | mode_a |

---

## 2. RQ1 — Throughput: quem vence em vazão?

**Resposta: mode_a domina em todas as cargas.**

- Em carga **baixa (20 msg/s)**: mode_a e mode_c são praticamente iguais (≈19,5 msg/s). mode_b já perde 28% da vazão pela taxa estática de 12 msg/s.
- Em carga **moderada (32 msg/s)**: mode_c despenca para 7,68 msg/s — menos que mode_b (13,64 msg/s). Isso é o sinal de que o controlador adaptativo está se sabotando.
- Em **sobrecarga (60 msg/s)**: mode_a processa 51,7 msg/s. mode_b trava em 14 msg/s; mode_c em 7,58 msg/s. A diferença é de **3,7× e 6,8×**, respectivamente.

**Insight:** a capacidade real do consumidor (custo de 20 ms/msg) suporta ≈ 50 msg/s. mode_a explora esse teto; os outros dois ficam muito abaixo sem necessidade técnica.

---

## 3. RQ2 — Latência p95 e Backlog: quem acumula menos fila?

**Resposta: mode_a é melhor até carga alta; apenas em sobrecarga começa a acumular.**

### Comportamento do backlog por modo

```
Carga baixa   →  mode_a: 0 msg   mode_b: 2.445 msg   mode_c: 0 msg
Carga moderada →  mode_a: 0 msg   mode_b: 6.104 msg   mode_c: 6.354 msg
Carga alta    →  mode_a: 0,4 msg  mode_b: 9.743 msg   mode_c: 10.042 msg
Sobrecarga    →  mode_a: 2.604 msg mode_b: 14.402 msg  mode_c: 14.600 msg
```

**Insight crítico sobre mode_b:**
- A taxa estática de **12 msg/s** é menor que a **menor carga testada (20 msg/s)**.  
- Isso garante que mode_b acumule fila em **100% dos cenários testados**, mesmo quando o sistema tinha CPU sobrando.
- Reconfigurando a taxa estática para ≈ 42 msg/s (ponto de saturação real), mode_b provavelmente zeraria o backlog até carga alta.

**Insight crítico sobre mode_c:**
- Em carga moderada, mode_c acumula **mais backlog que mode_b** (6.354 vs 6.104).
- Em carga alta e sobrecarga, também pior que mode_b.
- Isso indica **realimentação negativa**: ao ver backlog crescendo, o controlador **reduz a taxa**, o que piora ainda mais o backlog — ciclo vicioso.

---

## 4. RQ3 — Custo computacional vs. Estabilidade

**Resposta: os modos controlados economizam CPU, mas o custo em fila é desproporcional.**

| Carga | Economia de CPU mode_c vs mode_a | Custo em backlog |
|-------|----------------------------------|------------------|
| Baixa | 0 p.p. (ambos ≈ 48%) | 0 (neutro) |
| Moderada | −56,5 p.p. (15,4% vs 71,9%) | +6.354 mensagens |
| Alta | −79,5 p.p. (15,3% vs 94,8%) | +10.042 mensagens |
| Sobrecarga | −83,7 p.p. (15,1% vs 98,8%) | +14.600 mensagens |

**Insight:** em carga baixa, mode_c é a escolha ideal — mesmo desempenho que mode_a, com possibilidade de liberar CPU para outros serviços no mesmo host. Em qualquer carga acima de baixa, a economia não compensa.

**Ponto de inflexão real:** o sistema satura em ≈ 44 msg/s (CPU ≈ 95% no mode_a). Até esse ponto, mode_a é superior em tudo. Acima disso, nenhum dos três modos é completamente estável.

---

## 5. RQ4 — Adaptativo supera Estático?

**Resposta: NÃO na configuração atual. mode_b supera mode_c em 3 dos 4 perfis.**

| Métrica | mode_b vs mode_c (carga moderada) |
|---------|-----------------------------------|
| Throughput | mode_b: 13,64 vs mode_c: 7,68 → **mode_b +77%** |
| Latência p95 | mode_b: 199.233 ms vs mode_c: 207.341 ms → **mode_b melhor** |
| Backlog | mode_b: 6.104 vs mode_c: 6.354 → **mode_b melhor** |
| CPU | mode_b: 24,9% vs mode_c: 15,4% → mode_c usa menos CPU |

**Única vantagem real de mode_c:** carga baixa, onde mantém backlog nulo como mode_a enquanto usa menos CPU que ambos.

---

## 6. Insights Valiosos

### 🔴 Bug de Design: taxa estática mal dimensionada
A taxa de `mode_b` foi configurada em **12 msg/s**, mas a menor carga testada é **20 msg/s**. Isso torna mode_b artificialmente ruim em todos os cenários. Um valor correto seria ≈ 40 msg/s (próximo ao teto real do consumidor).

### 🔴 Bug de Lógica: realimentação negativa no mode_c
O controlador adaptativo reduz a taxa quando detecta backlog alto. Mas backlog alto significa que **o consumidor deveria processar mais rápido, não mais devagar**. A lógica está invertida para o sinal de backlog.

**Fix sugerido:**
```python
# Lógica atual (errada para backlog):
r(t+1) = r(t) * (1 - k * (score(t) - θ))
# score alto → r diminui → backlog piora

# Lógica correta:
# Quando backlog_norm alto → aumentar taxa (não reduzir)
# Quando cpu_norm alto → reduzir taxa
# Separar os sinais ao invés de agregá-los num único score
```

### 🟡 Saturação real ≈ 44 msg/s
O modo_a com custo de 20 ms/msg processa no máximo ≈ 50 msg/s (1000 ms / 20 ms = 50). Com overhead, o teto prático é ≈ 44 msg/s antes de acumular backlog. Qualquer política que fique abaixo disso sob cargas menores é artificialmente limitante.

### 🟡 mode_c é competitivo apenas em carga baixa
Na carga de 20 msg/s, mode_c praticamente iguala mode_a em throughput e latência, consumindo a mesma CPU. Esse é o único cenário onde o controle adaptativo agrega valor real na versão atual.

### 🟢 Oportunidade clara de melhora para mode_c
Três ajustes simples poderiam inverter o resultado:
1. **Inverter o sinal do backlog:** backlog alto → aumentar taxa (até o limite de CPU)
2. **Aumentar o ganho `k`:** a resposta atual é muito lenta (k=0,1)
3. **Taxa mínima mais alta:** o piso de 5 msg/s é baixo demais; com 20 msg/s chegando, nunca deve cair abaixo de 15 msg/s

### 🟢 Pipeline é reprodutível e instrumentado
O projeto entrega um ambiente completo (Docker Compose + Makefile + scripts de análise) que permite testar qualquer nova política com `make pipeline-analysis` sem modificar infraestrutura.

---

## 7. Resposta Direta às Hipóteses

| Hipótese | Resultado | Justificativa |
|----------|-----------|---------------|
| H1: controle → menor backlog e variabilidade | ❌ REFUTADA | Ambos os modos controlados acumulam muito mais backlog que mode_a |
| H2: controle → menor latência p95 em sobrecarga | ❌ REFUTADA | mode_b e mode_c têm latência p95 5–6× maior que mode_a mesmo em sobrecarga |
| H3: adaptativo → melhor que estático | ❌ REFUTADA (na config. atual) | mode_b supera mode_c em 3/4 perfis de carga |

**Conclusão geral:** as hipóteses foram refutadas na configuração atual, mas pelos motivos identificados (taxa estática mal dimensionada + lógica invertida no adaptativo), não por limitação fundamental do conceito de controle de fluxo.

---

## 8. Recomendações para Trabalhos Futuros

1. **Reconfigurar mode_b** com taxa ≈ 40 msg/s e re-executar o experimento
2. **Corrigir a lógica de mode_c**: separar sinais de backlog (aumentar taxa) e CPU (reduzir taxa)
3. **Testar cargas com rajadas** (burst de 2–3× a carga base por 10–30 s)
4. **Aumentar repetições** para 10–15 nos cenários de sobrecarga (maior variabilidade)
5. **Medir variabilidade intra-janela** (desvio do throughput por janela de 10 s)
6. **Testar múltiplos consumidores** — a política adaptativa pode ser mais efetiva com escalonamento horizontal

---

*Gerado em 2026-06-15 · Dados: `data/raw/pipeline_experiment_rq3.csv` · Artefatos: `results/pipeline_rqs/`*
