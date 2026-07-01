from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt


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

METRICS = [
    ("throughput_messages_s", "Throughput (msg/s)", "throughput.png"),
    ("latency_p95_ms", "Latencia p95 (ms)", "latency_p95.png"),
    ("backlog", "Backlog (mensagens)", "backlog.png"),
    ("cpu_percent", "CPU (%)", "cpu_percent.png"),
    ("memory_mb", "Memoria (MB)", "memory_mb.png"),
    ("backlog_sigma_second_half", "Sigma do backlog (2a metade)", "backlog_sigma_second_half.png"),
    ("cpu_mean_second_half", "CPU media (2a metade, %)", "cpu_mean_second_half.png"),
]


def load_summary(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    summary = payload.get("summary", [])
    if not isinstance(summary, list):
        raise ValueError("Campo 'summary' invalido no JSON de entrada.")
    return summary


def group_by_mode(rows: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        mode = str(row["mode"])
        grouped[mode].append(row)
    for mode_rows in grouped.values():
        mode_rows.sort(
            key=lambda item: (
                LOAD_PROFILE_ORDER.index(str(item["load_profile"])) if str(item.get("load_profile", "")) in LOAD_PROFILE_ORDER else 99,
                int(item["producer_rate"]),
            )
        )
    return grouped


def plot_metric(rows: list[dict[str, object]], metric: str, label: str, output_path: Path) -> None:
    grouped = group_by_mode(rows)
    x_profiles = [profile for profile in LOAD_PROFILE_ORDER if any(str(row.get("load_profile", "")) == profile for row in rows)]
    if not x_profiles:
        x_profiles = LOAD_PROFILE_ORDER

    x_positions = list(range(len(x_profiles)))

    fig, ax = plt.subplots(figsize=(8, 5))
    for mode in ["mode_a", "mode_b", "mode_c"]:
        mode_rows = grouped.get(mode, [])
        if not mode_rows:
            continue

        by_profile = {str(row.get("load_profile", "")): row for row in mode_rows}
        mean_values: list[float] = []
        error_values: list[float] = []
        for profile in x_profiles:
            row = by_profile.get(profile)
            if row is None:
                mean_values.append(float("nan"))
                error_values.append(float("nan"))
                continue
            mean_values.append(float(row[f"{metric}_mean"]))
            error_values.append(float(row.get(f"{metric}_ci95", row[f"{metric}_stdev"])))

        ax.errorbar(
            x_positions,
            mean_values,
            yerr=error_values,
            marker="o",
            linewidth=2,
            capsize=4,
            label=MODE_LABELS[mode],
            color=MODE_COLORS[mode],
        )

    ax.set_title(label)
    ax.set_xlabel("Perfil de carga")
    ax.set_xticks(x_positions)
    ax.set_xticklabels([LOAD_PROFILE_LABELS.get(profile, profile) for profile in x_profiles])
    ax.set_ylabel(label)
    ax.grid(True, linestyle="--", alpha=0.35)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera graficos PNG a partir do resumo do experimento.")
    parser.add_argument("--input", default="data/processed/pipeline_summary_rq3.json")
    parser.add_argument("--output-dir", default="results/plots_rq3")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = load_summary(input_path)
    for metric, label, filename in METRICS:
        plot_metric(rows, metric, label, output_dir / filename)

    print(f"Graficos salvos em {output_dir}")


if __name__ == "__main__":
    main()
