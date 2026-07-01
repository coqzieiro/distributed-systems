from __future__ import annotations

import argparse
import csv
import json
import shutil
import statistics
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt


SCENARIO_ORDER = ["baseline_estavel", "churn_moderado", "churn_alto"]
STRATEGY_ORDER = ["cached", "centralized"]
STRATEGY_LABELS = {"cached": "Cache local", "centralized": "Centralizada"}
STRATEGY_COLORS = {"cached": "#1f77b4", "centralized": "#ff7f0e"}
REQUIRED_COLUMNS = {
    "scenario",
    "strategy",
    "requests",
    "latency_mean_ms",
    "latency_p95_ms",
    "throughput_req_s",
    "invalid_endpoint_rate",
}
METRICS = [
    ("latency_mean_ms", "Latencia media (ms)", "latency_mean_ms"),
    ("latency_p95_ms", "Latencia p95 (ms)", "latency_p95_ms"),
    ("throughput_req_s", "Throughput (req/s)", "throughput_req_s"),
    ("invalid_endpoint_rate", "Endpoint invalido (%)", "invalid_endpoint_rate"),
]
T_CRITICAL_95 = {
    1: 12.706,
    2: 4.303,
    3: 3.182,
    4: 2.776,
    5: 2.571,
    6: 2.447,
    7: 2.365,
    8: 2.306,
    9: 2.262,
    10: 2.228,
}


def mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def stdev(values: list[float]) -> float:
    return statistics.stdev(values) if len(values) > 1 else 0.0


def ci95(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    t_value = T_CRITICAL_95.get(len(values) - 1, 1.96)
    return t_value * stdev(values) / (len(values) ** 0.5)


def reduction_percent(old_value: float, new_value: float) -> float:
    if old_value == 0:
        return 0.0
    return ((old_value - new_value) / old_value) * 100


def delta_percent(new_value: float, old_value: float) -> float:
    if old_value == 0:
        return 0.0
    return ((new_value - old_value) / old_value) * 100


def expected_csv_message(raw_input: Path) -> str:
    columns = [
        "repetition",
        "scenario",
        "strategy",
        "requests",
        "latency_mean_ms",
        "latency_p95_ms",
        "throughput_req_s",
        "invalid_endpoint_rate",
        "invalid_endpoint_count",
    ]
    example = ["1", "baseline_estavel", "cached", "600", "1.89", "3.66", "154.86", "0.0000", "0"]
    return (
        f"CSV bruto nao encontrado: {raw_input}\n"
        "Este script nao coleta nem simula dados. Primeiro rode o experimento real na VM e salve o CSV bruto nesse caminho, "
        "ou informe outro arquivo com --raw-input.\n\n"
        "Colunas obrigatorias:\n"
        f"  {', '.join(sorted(REQUIRED_COLUMNS))}\n\n"
        "Exemplo de cabecalho:\n"
        f"  {','.join(columns)}\n"
        "Exemplo de linha:\n"
        f"  {','.join(example)}\n"
    )


def clean_outputs(output_root: Path, raw_input: Path, clean_raw: bool) -> None:
    targets = [
        output_root / "data/processed/discovery_summary.json",
        output_root / "data/processed/discovery_metrics",
        output_root / "data/processed/discovery_rqs",
        output_root / "results/discovery",
        output_root / "docs/checkpoint4/generated",
    ]
    if clean_raw:
        targets.append(raw_input)
    for target in targets:
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()


def read_csv_rows(raw_input: Path) -> list[dict[str, Any]]:
    if not raw_input.exists():
        raise FileNotFoundError(expected_csv_message(raw_input))

    with raw_input.open(encoding="utf-8") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise ValueError(f"CSV sem cabecalho: {raw_input}")
        missing = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing:
            raise ValueError(f"CSV {raw_input} nao possui colunas obrigatorias: {', '.join(sorted(missing))}")
        rows = list(reader)

    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        scenario = row["scenario"].strip()
        strategy = row["strategy"].strip()
        if scenario not in SCENARIO_ORDER:
            raise ValueError(f"Linha {index}: scenario invalido '{scenario}'. Esperado: {', '.join(SCENARIO_ORDER)}")
        if strategy not in STRATEGY_ORDER:
            raise ValueError(f"Linha {index}: strategy invalida '{strategy}'. Esperado: {', '.join(STRATEGY_ORDER)}")
        try:
            normalized.append(
                {
                    "repetition": row.get("repetition") or str(index),
                    "scenario": scenario,
                    "strategy": strategy,
                    "requests": float(row["requests"]),
                    "latency_mean_ms": float(row["latency_mean_ms"]),
                    "latency_p95_ms": float(row["latency_p95_ms"]),
                    "throughput_req_s": float(row["throughput_req_s"]),
                    "invalid_endpoint_rate": float(row["invalid_endpoint_rate"]),
                    "invalid_endpoint_count": float(row.get("invalid_endpoint_count") or 0),
                }
            )
        except ValueError as error:
            raise ValueError(f"Linha {index}: valor numerico invalido no CSV") from error

    required_pairs = {(scenario, strategy) for scenario in SCENARIO_ORDER for strategy in STRATEGY_ORDER}
    present_pairs = {(str(row["scenario"]), str(row["strategy"])) for row in normalized}
    missing_pairs = sorted(required_pairs - present_pairs)
    if missing_pairs:
        formatted = ", ".join(f"{scenario}/{strategy}" for scenario, strategy in missing_pairs)
        raise ValueError(f"CSV incompleto. Faltam combinacoes scenario/strategy: {formatted}")
    return normalized


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def metric_suffix(metric: str) -> str:
    return "invalid_endpoint_percent" if metric == "invalid_endpoint_rate" else metric


def aggregate_runs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["scenario"]), str(row["strategy"])), []).append(row)

    summary: list[dict[str, Any]] = []
    for scenario in SCENARIO_ORDER:
        for strategy in STRATEGY_ORDER:
            items = grouped[(scenario, strategy)]
            payload: dict[str, Any] = {
                "scenario": scenario,
                "strategy": strategy,
                "runs": len(items),
                "requests_mean": round(mean([float(item["requests"]) for item in items]), 2),
            }
            for metric, _, _ in METRICS:
                values = [float(item[metric]) for item in items]
                if metric == "invalid_endpoint_rate":
                    values = [value * 100 for value in values]
                suffix = metric_suffix(metric)
                payload[f"{suffix}_mean"] = round(mean(values), 4)
                payload[f"{suffix}_stdev"] = round(stdev(values), 4)
                payload[f"{suffix}_ci95"] = round(ci95(values), 4)
            summary.append(payload)
    return summary


def summary_lookup(summary: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(str(row["scenario"]), str(row["strategy"])): row for row in summary}


def build_rq_rows(summary: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    lookup = summary_lookup(summary)
    rq1: list[dict[str, Any]] = []
    rq2: list[dict[str, Any]] = []
    rq3: list[dict[str, Any]] = []
    rq4: list[dict[str, Any]] = []
    matrix: list[dict[str, Any]] = []

    for scenario in SCENARIO_ORDER:
        cached = lookup[(scenario, "cached")]
        centralized = lookup[(scenario, "centralized")]
        cached_p95 = float(cached["latency_p95_ms_mean"])
        centralized_p95 = float(centralized["latency_p95_ms_mean"])
        cached_throughput = float(cached["throughput_req_s_mean"])
        centralized_throughput = float(centralized["throughput_req_s_mean"])
        cached_invalid = float(cached["invalid_endpoint_percent_mean"])
        centralized_invalid = float(centralized["invalid_endpoint_percent_mean"])

        p95_reduction_ms = centralized_p95 - cached_p95
        p95_reduction_pct = reduction_percent(centralized_p95, cached_p95)
        throughput_delta = cached_throughput - centralized_throughput
        throughput_delta_pct = delta_percent(cached_throughput, centralized_throughput)
        invalid_delta_pp = cached_invalid - centralized_invalid

        if invalid_delta_pp == 0:
            rq4_answer = "Sim"
            rq4_note = "Ganho sem inconsistencia observada."
        elif invalid_delta_pp <= 2:
            rq4_answer = "Parcialmente"
            rq4_note = "Compensa se a aplicacao tolerar inconsistencia baixa."
        else:
            rq4_answer = "Parcialmente"
            rq4_note = "Exige mitigacao por TTL menor, invalidacao ativa ou health check."

        rq1.append(
            {
                "scenario": scenario,
                "cached_p95_ms": round(cached_p95, 4),
                "centralized_p95_ms": round(centralized_p95, 4),
                "reduction_ms": round(p95_reduction_ms, 4),
                "reduction_percent": round(p95_reduction_pct, 4),
                "answer": "Sim" if p95_reduction_ms > 0 else "Nao",
            }
        )
        rq2.append(
            {
                "scenario": scenario,
                "cached_throughput_req_s": round(cached_throughput, 4),
                "centralized_throughput_req_s": round(centralized_throughput, 4),
                "delta_req_s": round(throughput_delta, 4),
                "delta_percent": round(throughput_delta_pct, 4),
                "answer": "Sim" if throughput_delta >= 0 else "Nao",
            }
        )
        rq3.append(
            {
                "scenario": scenario,
                "cached_invalid_percent": round(cached_invalid, 4),
                "centralized_invalid_percent": round(centralized_invalid, 4),
                "delta_percentage_points": round(invalid_delta_pp, 4),
                "answer": "Nao se aplica" if scenario == "baseline_estavel" else ("Sim" if invalid_delta_pp > 0 else "Nao"),
            }
        )
        rq4.append(
            {
                "scenario": scenario,
                "p95_reduction_percent": round(p95_reduction_pct, 4),
                "throughput_delta_percent": round(throughput_delta_pct, 4),
                "invalid_delta_percentage_points": round(invalid_delta_pp, 4),
                "answer": rq4_answer,
                "note": rq4_note,
            }
        )
        matrix.append(
            {
                "scenario": scenario,
                "rq1": rq1[-1]["answer"],
                "rq2": rq2[-1]["answer"],
                "rq3": rq3[-1]["answer"],
                "rq4": rq4[-1]["answer"],
            }
        )

    return {"rq1_latency_p95": rq1, "rq2_throughput": rq2, "rq3_invalid_endpoints": rq3, "rq4_tradeoff": rq4, "rq_matrix": matrix}


def write_metric_tables(summary: list[dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for metric, label, filename in METRICS:
        suffix = metric_suffix(metric)
        rows = [
            {
                "scenario": row["scenario"],
                "strategy": row["strategy"],
                "metric": label,
                "mean": row[f"{suffix}_mean"],
                "stdev": row[f"{suffix}_stdev"],
                "ci95": row[f"{suffix}_ci95"],
            }
            for row in summary
        ]
        write_csv(output_dir / f"{filename}.csv", rows, ["scenario", "strategy", "metric", "mean", "stdev", "ci95"])


def write_rq_tables(rq_rows: dict[str, list[dict[str, Any]]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in rq_rows.items():
        if rows:
            write_csv(output_dir / f"{name}.csv", rows, list(rows[0].keys()))


def plot_metric(summary: list[dict[str, Any]], metric: str, label: str, filename: str, output_dir: Path) -> None:
    suffix = metric_suffix(metric)
    x_positions = list(range(len(SCENARIO_ORDER)))
    width = 0.36

    fig, ax = plt.subplots(figsize=(8.8, 5.2))
    for index, strategy in enumerate(STRATEGY_ORDER):
        offset = -width / 2 if index == 0 else width / 2
        rows = [row for row in summary if row["strategy"] == strategy]
        rows.sort(key=lambda row: SCENARIO_ORDER.index(str(row["scenario"])))
        means = [float(row[f"{suffix}_mean"]) for row in rows]
        errors = [float(row[f"{suffix}_ci95"]) for row in rows]
        ax.bar(
            [position + offset for position in x_positions],
            means,
            width=width,
            yerr=errors,
            capsize=4,
            color=STRATEGY_COLORS[strategy],
            label=STRATEGY_LABELS[strategy],
        )

    ax.set_title(label)
    ax.set_ylabel(label)
    ax.set_xticks(x_positions)
    ax.set_xticklabels([scenario.replace("_", "\n") for scenario in SCENARIO_ORDER])
    ax.grid(True, axis="y", linestyle="--", alpha=0.35)
    ax.legend()
    fig.tight_layout()
    output_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_dir / f"{filename}.png", dpi=170)
    plt.close(fig)


def plot_rq_bars(rows: list[dict[str, Any]], value_key: str, ylabel: str, title: str, output_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8.4, 5.0))
    values = [float(row[value_key]) for row in rows]
    ax.bar([row["scenario"].replace("_", "\n") for row in rows], values, color="#1f77b4")
    ax.axhline(0, color="#444444", linewidth=1)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.grid(True, axis="y", linestyle="--", alpha=0.35)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=170)
    plt.close(fig)


def plot_rq4_tradeoff(rows: list[dict[str, Any]], output_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8.6, 5.2))
    x_values = [float(row["invalid_delta_percentage_points"]) for row in rows]
    y_values = [float(row["p95_reduction_percent"]) for row in rows]
    sizes = [140 + max(float(row["throughput_delta_percent"]), 0) * 35 for row in rows]
    ax.scatter(x_values, y_values, s=sizes, color="#1f77b4", alpha=0.82)
    for row in rows:
        ax.annotate(
            str(row["scenario"]).replace("_", " "),
            (float(row["invalid_delta_percentage_points"]), float(row["p95_reduction_percent"])),
            textcoords="offset points",
            xytext=(8, 6),
            fontsize=9,
        )
    ax.set_title("RQ4 - Ganho de desempenho vs. risco de inconsistencia")
    ax.set_xlabel("Aumento de endpoints invalidos com cache (p.p.)")
    ax.set_ylabel("Reducao da latencia p95 com cache (%)")
    ax.grid(True, linestyle="--", alpha=0.35)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=170)
    plt.close(fig)


def plot_rq_matrix(rows: list[dict[str, Any]], output_path: Path) -> None:
    headers = ["Cenario", "RQ1", "RQ2", "RQ3", "RQ4"]
    values = [[row["scenario"], row["rq1"], row["rq2"], row["rq3"], row["rq4"]] for row in rows]
    fig, ax = plt.subplots(figsize=(9.4, 3.0))
    ax.axis("off")
    table = ax.table(cellText=values, colLabels=headers, cellLoc="center", loc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.55)
    for (row, _), cell in table.get_celld().items():
        if row == 0:
            cell.set_facecolor("#1b4f72")
            cell.set_text_props(color="white", weight="bold")
        elif row % 2 == 0:
            cell.set_facecolor("#edf3f8")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def markdown_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    headers = list(rows[0].keys())
    output = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        output.append("| " + " | ".join(str(row[header]) for header in headers) + " |")
    return "\n".join(output)


def write_markdown_docs(summary: list[dict[str, Any]], rq_rows: dict[str, list[dict[str, Any]]], docs_dir: Path) -> None:
    docs_dir.mkdir(parents=True, exist_ok=True)
    docs = {
        "RQ1_LATENCIA_P95.md": ("RQ1 - Cache local reduz a latencia p95?", rq_rows["rq1_latency_p95"]),
        "RQ2_THROUGHPUT.md": ("RQ2 - Cache local preserva ou aumenta throughput?", rq_rows["rq2_throughput"]),
        "RQ3_ENDPOINTS_INVALIDOS.md": ("RQ3 - Cache local aumenta endpoints invalidos em churn?", rq_rows["rq3_invalid_endpoints"]),
        "RQ4_TRADEOFF.md": ("RQ4 - O ganho compensa o risco?", rq_rows["rq4_tradeoff"]),
    }
    for filename, (title, rows) in docs.items():
        (docs_dir / filename).write_text(f"# {title}\n\n{markdown_table(rows)}\n", encoding="utf-8")

    summary_content = f"""# Resultados Gerados - Descoberta de Servicos

Este diretorio e gerado por `scripts/run_service_discovery_analysis.py` a partir de um CSV bruto real.

## Dados consolidados por estrategia

{markdown_table(summary)}

## Matriz RQ

{markdown_table(rq_rows["rq_matrix"])}

## Artefatos gerados

- Tabelas por metrica: `data/processed/discovery_metrics/`.
- Tabelas por requisito: `data/processed/discovery_rqs/`.
- Graficos por metrica: `results/discovery/metrics/`.
- Graficos por requisito: `results/discovery/rqs/`.
"""
    (docs_dir / "README.md").write_text(summary_content, encoding="utf-8")


def analyze(raw_input: Path, output_root: Path) -> None:
    rows = read_csv_rows(raw_input)
    summary = aggregate_runs(rows)
    rq_rows = build_rq_rows(summary)

    summary_path = output_root / "data/processed/discovery_summary.json"
    metric_tables_dir = output_root / "data/processed/discovery_metrics"
    rq_tables_dir = output_root / "data/processed/discovery_rqs"
    metric_plots_dir = output_root / "results/discovery/metrics"
    rq_plots_dir = output_root / "results/discovery/rqs"
    docs_dir = output_root / "docs/checkpoint4/generated"

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps({"summary": summary, "requirements": rq_rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    write_metric_tables(summary, metric_tables_dir)
    write_rq_tables(rq_rows, rq_tables_dir)

    for metric, label, filename in METRICS:
        plot_metric(summary, metric, label, filename, metric_plots_dir)
    plot_rq_bars(rq_rows["rq1_latency_p95"], "reduction_percent", "Reducao p95 (%)", "RQ1 - Reducao de latencia p95", rq_plots_dir / "rq1_latency_p95.png")
    plot_rq_bars(rq_rows["rq2_throughput"], "delta_percent", "Delta throughput (%)", "RQ2 - Ganho/preservacao de throughput", rq_plots_dir / "rq2_throughput.png")
    plot_rq_bars(rq_rows["rq3_invalid_endpoints"], "delta_percentage_points", "Aumento de endpoints invalidos (p.p.)", "RQ3 - Endpoints invalidos em churn", rq_plots_dir / "rq3_invalid_endpoints.png")
    plot_rq4_tradeoff(rq_rows["rq4_tradeoff"], rq_plots_dir / "rq4_tradeoff.png")
    plot_rq_matrix(rq_rows["rq_matrix"], rq_plots_dir / "rq_matrix.png")
    write_markdown_docs(summary, rq_rows, docs_dir)

    print(f"CSV bruto usado: {raw_input}")
    print(f"Resumo JSON: {summary_path}")
    print(f"Tabelas por metrica: {metric_tables_dir}")
    print(f"Tabelas por RQ: {rq_tables_dir}")
    print(f"Graficos por metrica: {metric_plots_dir}")
    print(f"Graficos por RQ: {rq_plots_dir}")
    print(f"Markdown gerado: {docs_dir}")


def resolve_raw_input(output_root: Path, raw_input_arg: str) -> Path:
    raw_input = Path(raw_input_arg)
    if raw_input.is_absolute():
        return raw_input
    return output_root / raw_input


def main() -> None:
    parser = argparse.ArgumentParser(description="Consolida CSV real de descoberta de servicos para RQ1-RQ4.")
    parser.add_argument("--raw-input", default="data/raw/discovery_experiment_runs.csv", help="CSV bruto real gerado na VM.")
    parser.add_argument("--output-root", default=".", help="Raiz onde data/, results/ e docs/ serao gerados.")
    parser.add_argument("--clean", action="store_true", help="Remove resultados processados/graficos antes de analisar.")
    parser.add_argument("--clean-raw", action="store_true", help="Tambem remove o CSV bruto informado em --raw-input.")
    parser.add_argument("--clean-only", action="store_true", help="Apenas remove resultados e encerra.")
    args = parser.parse_args()

    output_root = Path(args.output_root)
    raw_input = resolve_raw_input(output_root, args.raw_input)

    if args.clean:
        clean_outputs(output_root, raw_input=raw_input, clean_raw=args.clean_raw)
    if args.clean_only:
        print("Resultados removidos.")
        return

    try:
        analyze(raw_input, output_root)
    except (FileNotFoundError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
