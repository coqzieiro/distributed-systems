from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt


MODES = ["mode_a", "mode_b", "mode_c"]
MODE_LABELS = {
    "mode_a": "Modo A",
    "mode_b": "Modo B",
    "mode_c": "Modo C",
}
MODE_COLORS = {
    "mode_a": "#1f77b4",
    "mode_b": "#d62728",
    "mode_c": "#2ca02c",
}
LOAD_PROFILE_ORDER = ["baixa", "moderada", "alta", "sobrecarga"]
LOAD_PROFILE_LABELS = {
    "baixa": "Baixa",
    "moderada": "Moderada",
    "alta": "Alta",
    "sobrecarga": "Sobrecarga",
}


def load_summary(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        raise FileNotFoundError(
            (
                f"Arquivo de resumo nao encontrado: {path}\n"
                "Execute antes: make pipeline-summarize (ou make pipeline-analysis)."
            )
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("summary")
    if not isinstance(rows, list):
        raise ValueError("Campo 'summary' ausente ou invalido no JSON de entrada.")
    return rows


def ordered_load_profiles(rows: list[dict[str, object]]) -> list[str]:
    present = {str(row.get("load_profile", "")) for row in rows}
    known = [profile for profile in LOAD_PROFILE_ORDER if profile in present]
    unknown = sorted(present - set(LOAD_PROFILE_ORDER))
    return known + unknown


def index_by_load_and_mode(rows: list[dict[str, object]]) -> dict[tuple[str, str], dict[str, object]]:
    index: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows:
        index[(str(row["load_profile"]), str(row["mode"]))] = row
    return index


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_rq1_latency_table(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    loads = ordered_load_profiles(rows)
    index = index_by_load_and_mode(rows)
    table: list[dict[str, object]] = []

    for load in loads:
        mode_values: dict[str, float] = {}
        for mode in MODES:
            item = index.get((load, mode))
            mode_values[mode] = float(item["latency_p95_ms_mean"]) if item else float("nan")

        available = {mode: value for mode, value in mode_values.items() if value == value}
        best_mode = min(available, key=available.get) if available else "n/a"
        best_value = available[best_mode] if available else float("nan")

        row: dict[str, object] = {
            "load_profile": load,
            "winner_mode": best_mode,
            "winner_latency_p95_ms": round(best_value, 4) if best_value == best_value else "n/a",
        }
        for mode in MODES:
            value = mode_values[mode]
            delta = value - best_value if value == value and best_value == best_value else float("nan")
            row[f"{mode}_latency_p95_ms"] = round(value, 4) if value == value else "n/a"
            row[f"{mode}_delta_vs_best_ms"] = round(delta, 4) if delta == delta else "n/a"
        table.append(row)

    return table


def build_rq2_throughput_table(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    loads = ordered_load_profiles(rows)
    index = index_by_load_and_mode(rows)
    table: list[dict[str, object]] = []

    for load in loads:
        mode_values: dict[str, float] = {}
        for mode in MODES:
            item = index.get((load, mode))
            mode_values[mode] = float(item["throughput_messages_s_mean"]) if item else float("nan")

        available = {mode: value for mode, value in mode_values.items() if value == value}
        best_mode = max(available, key=available.get) if available else "n/a"
        best_value = available[best_mode] if available else float("nan")

        row: dict[str, object] = {
            "load_profile": load,
            "winner_mode": best_mode,
            "winner_throughput_messages_s": round(best_value, 4) if best_value == best_value else "n/a",
        }
        for mode in MODES:
            value = mode_values[mode]
            delta = best_value - value if value == value and best_value == best_value else float("nan")
            row[f"{mode}_throughput_messages_s"] = round(value, 4) if value == value else "n/a"
            row[f"{mode}_gap_to_best_messages_s"] = round(delta, 4) if delta == delta else "n/a"
        table.append(row)

    return table


def build_rq3_invalid_endpoints_table(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    has_invalid_metric = any("invalid_endpoint_rate_mean" in row for row in rows)
    loads = ordered_load_profiles(rows)

    table: list[dict[str, object]] = []
    for load in loads:
        table.append(
            {
                "load_profile": load,
                "status": "disponivel" if has_invalid_metric else "indisponivel",
                "detail": (
                    "Metrica invalid_endpoint_rate_mean presente no resumo."
                    if has_invalid_metric
                    else "CSV do pipeline nao contem metrica de endpoint invalido; RQ3 nao pode ser calculado para os modos A/B/C com os dados atuais."
                ),
            }
        )
    return table


def normalize(values: dict[str, float], invert: bool = False) -> dict[str, float]:
    available = {k: v for k, v in values.items() if v == v}
    if not available:
        return {k: float("nan") for k in values}
    min_v = min(available.values())
    max_v = max(available.values())
    if abs(max_v - min_v) < 1e-12:
        return {k: 1.0 if v == v else float("nan") for k, v in values.items()}

    normalized: dict[str, float] = {}
    for key, value in values.items():
        if value != value:
            normalized[key] = float("nan")
            continue
        raw = (value - min_v) / (max_v - min_v)
        normalized[key] = 1.0 - raw if invert else raw
    return normalized


def build_rq4_tradeoff_table(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    loads = ordered_load_profiles(rows)
    index = index_by_load_and_mode(rows)
    table: list[dict[str, object]] = []

    for load in loads:
        tp = {}
        lat = {}
        backlog = {}
        cpu = {}
        for mode in MODES:
            item = index.get((load, mode))
            tp[mode] = float(item["throughput_messages_s_mean"]) if item else float("nan")
            lat[mode] = float(item["latency_p95_ms_mean"]) if item else float("nan")
            backlog[mode] = float(item["backlog_mean"]) if item else float("nan")
            cpu[mode] = float(item["cpu_mean_second_half_mean"]) if item else float("nan")

        tp_n = normalize(tp, invert=False)
        lat_n = normalize(lat, invert=True)
        backlog_n = normalize(backlog, invert=True)
        cpu_n = normalize(cpu, invert=True)

        scores: dict[str, float] = {}
        for mode in MODES:
            components = [tp_n[mode], lat_n[mode], backlog_n[mode], cpu_n[mode]]
            valid = [value for value in components if value == value]
            scores[mode] = sum(valid) / len(valid) if valid else float("nan")

        available = {mode: score for mode, score in scores.items() if score == score}
        best_mode = max(available, key=available.get) if available else "n/a"

        row: dict[str, object] = {
            "load_profile": load,
            "winner_mode": best_mode,
            "winner_tradeoff_score": round(available[best_mode], 4) if available else "n/a",
        }
        for mode in MODES:
            row[f"{mode}_tradeoff_score"] = round(scores[mode], 4) if scores[mode] == scores[mode] else "n/a"
            row[f"{mode}_throughput_messages_s"] = round(tp[mode], 4) if tp[mode] == tp[mode] else "n/a"
            row[f"{mode}_latency_p95_ms"] = round(lat[mode], 4) if lat[mode] == lat[mode] else "n/a"
            row[f"{mode}_backlog"] = round(backlog[mode], 4) if backlog[mode] == backlog[mode] else "n/a"
            row[f"{mode}_cpu_mean_second_half"] = round(cpu[mode], 4) if cpu[mode] == cpu[mode] else "n/a"
        table.append(row)

    return table


def plot_lines(rows: list[dict[str, object]], metric_mean_key: str, title: str, y_label: str, output_path: Path) -> None:
    loads = ordered_load_profiles(rows)
    index = index_by_load_and_mode(rows)
    x_positions = list(range(len(loads)))

    fig, ax = plt.subplots(figsize=(8, 5))
    for mode in MODES:
        values = []
        for load in loads:
            item = index.get((load, mode))
            values.append(float(item[metric_mean_key]) if item else float("nan"))
        ax.plot(
            x_positions,
            values,
            marker="o",
            linewidth=2,
            color=MODE_COLORS[mode],
            label=MODE_LABELS[mode],
        )

    ax.set_title(title)
    ax.set_xlabel("Perfil de carga")
    ax.set_ylabel(y_label)
    ax.set_xticks(x_positions)
    ax.set_xticklabels([LOAD_PROFILE_LABELS.get(load, load) for load in loads])
    ax.grid(True, linestyle="--", alpha=0.35)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def plot_rq3_unavailable(table: list[dict[str, object]], output_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 2.8))
    ax.axis("off")
    text = table[0]["detail"] if table else "RQ3 sem dados."
    ax.text(0.01, 0.6, "RQ3 - Endpoints invalidos", fontsize=13, fontweight="bold", transform=ax.transAxes)
    ax.text(0.01, 0.3, str(text), fontsize=11, transform=ax.transAxes)
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def plot_tradeoff_scores(table: list[dict[str, object]], output_path: Path) -> None:
    loads = [str(row["load_profile"]) for row in table]
    x_positions = list(range(len(loads)))

    fig, ax = plt.subplots(figsize=(9, 5))
    width = 0.22
    offsets = {"mode_a": -width, "mode_b": 0.0, "mode_c": width}

    for mode in MODES:
        values = [float(row[f"{mode}_tradeoff_score"]) if row[f"{mode}_tradeoff_score"] != "n/a" else float("nan") for row in table]
        ax.bar(
            [x + offsets[mode] for x in x_positions],
            values,
            width=width,
            color=MODE_COLORS[mode],
            label=MODE_LABELS[mode],
        )

    ax.set_title("RQ4 - Tradeoff desempenho x custo por modo")
    ax.set_xlabel("Perfil de carga")
    ax.set_ylabel("Score de tradeoff (0-1)")
    ax.set_xticks(x_positions)
    ax.set_xticklabels([LOAD_PROFILE_LABELS.get(load, load) for load in loads])
    ax.set_ylim(0, 1.05)
    ax.grid(True, axis="y", linestyle="--", alpha=0.35)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def write_readme(output_dir: Path) -> None:
    content = """# Artefatos por requisito (pipeline)

Este diretorio contem tabelas e graficos por requisito, separados por modo (A, B, C).

- rq1_latency_p95_by_mode.csv / rq1_latency_p95_by_mode.png
- rq2_throughput_by_mode.csv / rq2_throughput_by_mode.png
- rq3_invalid_endpoints_by_mode.csv / rq3_invalid_endpoints_by_mode.png
- rq4_tradeoff_by_mode.csv / rq4_tradeoff_by_mode.png

Observacao sobre RQ3:
- Se o CSV de entrada nao tiver a metrica de endpoint invalido, o arquivo de RQ3 sera gerado como indisponivel.
"""
    (output_dir / "README.md").write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera tabelas e graficos por requisito para os modos A/B/C.")
    parser.add_argument("--input", default="data/processed/pipeline_summary_rq3.json")
    parser.add_argument("--output-dir", default="results/pipeline_rqs")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = load_summary(input_path)

    rq1_table = build_rq1_latency_table(rows)
    rq2_table = build_rq2_throughput_table(rows)
    rq3_table = build_rq3_invalid_endpoints_table(rows)
    rq4_table = build_rq4_tradeoff_table(rows)

    write_csv(
        output_dir / "rq1_latency_p95_by_mode.csv",
        list(rq1_table[0].keys()) if rq1_table else ["load_profile"],
        rq1_table,
    )
    write_csv(
        output_dir / "rq2_throughput_by_mode.csv",
        list(rq2_table[0].keys()) if rq2_table else ["load_profile"],
        rq2_table,
    )
    write_csv(
        output_dir / "rq3_invalid_endpoints_by_mode.csv",
        list(rq3_table[0].keys()) if rq3_table else ["load_profile", "status", "detail"],
        rq3_table,
    )
    write_csv(
        output_dir / "rq4_tradeoff_by_mode.csv",
        list(rq4_table[0].keys()) if rq4_table else ["load_profile"],
        rq4_table,
    )

    plot_lines(
        rows,
        metric_mean_key="latency_p95_ms_mean",
        title="RQ1 - Latencia p95 por modo",
        y_label="Latencia p95 (ms)",
        output_path=output_dir / "rq1_latency_p95_by_mode.png",
    )
    plot_lines(
        rows,
        metric_mean_key="throughput_messages_s_mean",
        title="RQ2 - Throughput por modo",
        y_label="Throughput (msg/s)",
        output_path=output_dir / "rq2_throughput_by_mode.png",
    )
    plot_rq3_unavailable(rq3_table, output_dir / "rq3_invalid_endpoints_by_mode.png")
    plot_tradeoff_scores(rq4_table, output_dir / "rq4_tradeoff_by_mode.png")

    write_readme(output_dir)
    print(f"Artefatos por requisito salvos em {output_dir}")


if __name__ == "__main__":
    main()
