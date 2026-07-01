from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from itertools import combinations
from pathlib import Path

from scipy import stats


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

METRICS = [
    "throughput_messages_s",
    "latency_p95_ms",
    "backlog",
    "backlog_sigma",
    "cpu_percent",
    "memory_mb",
    "backlog_sigma_second_half",
    "cpu_mean_second_half",
    "memory_mean_second_half",
]

LOAD_PROFILE_BY_RATE = {
    20: "baixa",
    32: "moderada",
    44: "alta",
    60: "sobrecarga",
}

LOAD_PROFILE_ORDER = {
    "baixa": 0,
    "moderada": 1,
    "alta": 2,
    "sobrecarga": 3,
}


def mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def stdev(values: list[float]) -> float:
    return statistics.stdev(values) if len(values) > 1 else 0.0


def ci95(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    degrees_of_freedom = len(values) - 1
    t_value = T_CRITICAL_95.get(degrees_of_freedom, 1.96)
    return t_value * stdev(values) / (len(values) ** 0.5)


def resolve_load_profile(row: dict[str, str]) -> str:
    raw_profile = (row.get("load_profile") or "").strip().lower()
    if raw_profile:
        return raw_profile
    producer_rate = int(row["producer_rate"])
    return LOAD_PROFILE_BY_RATE.get(producer_rate, f"carga_{producer_rate}")


def index_rows(
    rows: list[dict[str, str]],
) -> tuple[
    dict[tuple[str, int, str], list[dict[str, str]]],
    dict[tuple[str, int, str], dict[int, dict[str, str]]],
]:
    grouped: dict[tuple[str, int, str], list[dict[str, str]]] = defaultdict(list)
    grouped_by_rep: dict[tuple[str, int, str], dict[int, dict[str, str]]] = defaultdict(dict)

    for row in rows:
        producer_rate = int(row["producer_rate"])
        load_profile = resolve_load_profile(row)
        mode = row["mode"]
        repetition = int(row.get("repetition") or 0)
        key = (load_profile, producer_rate, mode)
        grouped[key].append(row)
        grouped_by_rep[key][repetition] = row

    return grouped, grouped_by_rep


def summarize_groups(grouped: dict[tuple[str, int, str], list[dict[str, str]]]) -> list[dict[str, object]]:
    summary_rows: list[dict[str, object]] = []
    for (load_profile, producer_rate, mode), items in sorted(
        grouped.items(), key=lambda item: (LOAD_PROFILE_ORDER.get(item[0][0], 99), item[0][1], item[0][2])
    ):
        summary: dict[str, object] = {
            "load_profile": load_profile,
            "producer_rate": producer_rate,
            "mode": mode,
            "runs": len(items),
        }
        for metric in METRICS:
            values = [float(item[metric]) for item in items]
            summary[f"{metric}_mean"] = round(mean(values), 3)
            summary[f"{metric}_stdev"] = round(stdev(values), 3)
            summary[f"{metric}_ci95"] = round(ci95(values), 3)
        summary_rows.append(summary)
    return summary_rows


def build_conclusions(summary_rows: list[dict[str, object]]) -> list[str]:
    conclusions: list[str] = []
    by_load: dict[tuple[str, int], list[dict[str, object]]] = defaultdict(list)
    for row in summary_rows:
        by_load[(str(row["load_profile"]), int(row["producer_rate"]))].append(row)

    for (load_profile, producer_rate), items in sorted(
        by_load.items(), key=lambda item: (LOAD_PROFILE_ORDER.get(item[0][0], 99), item[0][1])
    ):
        best_tp = max(items, key=lambda item: float(item["throughput_messages_s_mean"]))
        lowest_backlog = min(items, key=lambda item: float(item["backlog_mean"]))
        lowest_latency = min(items, key=lambda item: float(item["latency_p95_ms_mean"]))
        lowest_stability_cost = min(items, key=lambda item: float(item["backlog_sigma_second_half_mean"]))
        lowest_cpu = min(items, key=lambda item: float(item["cpu_mean_second_half_mean"]))
        conclusions.append(
            (
                f"Carga {load_profile} ({producer_rate} msg/s): melhor throughput em {best_tp['mode']} "
                f"({best_tp['throughput_messages_s_mean']} msg/s), menor backlog em "
                f"{lowest_backlog['mode']} ({lowest_backlog['backlog_mean']}), menor latencia em "
                f"{lowest_latency['mode']} ({lowest_latency['latency_p95_ms_mean']} ms), menor "
                f"variacao de backlog em {lowest_stability_cost['mode']} "
                f"({lowest_stability_cost['backlog_sigma_second_half_mean']}), menor CPU media "
                f"na segunda metade em {lowest_cpu['mode']} "
                f"({lowest_cpu['cpu_mean_second_half_mean']}%)."
            )
        )
    return conclusions


def paired_values(
    grouped_by_rep: dict[tuple[str, int, str], dict[int, dict[str, str]]],
    load_profile: str,
    producer_rate: int,
    mode_left: str,
    mode_right: str,
    metric: str,
) -> tuple[list[float], list[float]]:
    left_rows = grouped_by_rep.get((load_profile, producer_rate, mode_left), {})
    right_rows = grouped_by_rep.get((load_profile, producer_rate, mode_right), {})
    shared_repetitions = sorted(set(left_rows.keys()) & set(right_rows.keys()))
    left = [float(left_rows[rep][metric]) for rep in shared_repetitions]
    right = [float(right_rows[rep][metric]) for rep in shared_repetitions]
    return left, right


def run_statistical_tests(
    grouped_by_rep: dict[tuple[str, int, str], dict[int, dict[str, str]]]
) -> list[dict[str, object]]:
    tests: list[dict[str, object]] = []
    modes = ["mode_a", "mode_b", "mode_c"]

    load_pairs = sorted(
        {(load_profile, producer_rate) for (load_profile, producer_rate, _) in grouped_by_rep.keys()},
        key=lambda item: (LOAD_PROFILE_ORDER.get(item[0], 99), item[1]),
    )

    for load_profile, producer_rate in load_pairs:
        for mode_left, mode_right in combinations(modes, 2):
            for metric in METRICS:
                left, right = paired_values(grouped_by_rep, load_profile, producer_rate, mode_left, mode_right, metric)
                if len(left) < 3:
                    tests.append(
                        {
                            "load_profile": load_profile,
                            "producer_rate": producer_rate,
                            "metric": metric,
                            "mode_left": mode_left,
                            "mode_right": mode_right,
                            "n": len(left),
                            "normality_test": "shapiro_on_paired_diff",
                            "normality_p_value": None,
                            "test_used": "insufficient_samples",
                            "test_statistic": None,
                            "p_value": None,
                            "significant_0_05": None,
                            "mean_delta_left_minus_right": round(mean([a - b for a, b in zip(left, right)]), 6),
                        }
                    )
                    continue

                diffs = [a - b for a, b in zip(left, right)]
                shapiro_stat, shapiro_p = stats.shapiro(diffs)

                test_used = "paired_ttest" if shapiro_p > 0.05 else "wilcoxon_signed_rank"
                if all(abs(value) < 1e-12 for value in diffs):
                    test_stat = 0.0
                    p_value = 1.0
                    test_used = "all_diffs_zero"
                elif test_used == "paired_ttest":
                    test_result = stats.ttest_rel(left, right)
                    test_stat = float(test_result.statistic)
                    p_value = float(test_result.pvalue)
                else:
                    test_result = stats.wilcoxon(left, right, zero_method="wilcox", alternative="two-sided")
                    test_stat = float(test_result.statistic)
                    p_value = float(test_result.pvalue)

                tests.append(
                    {
                        "load_profile": load_profile,
                        "producer_rate": producer_rate,
                        "metric": metric,
                        "mode_left": mode_left,
                        "mode_right": mode_right,
                        "n": len(left),
                        "normality_test": "shapiro_on_paired_diff",
                        "normality_statistic": round(float(shapiro_stat), 6),
                        "normality_p_value": round(float(shapiro_p), 6),
                        "test_used": test_used,
                        "test_statistic": round(float(test_stat), 6),
                        "p_value": round(float(p_value), 6),
                        "significant_0_05": bool(p_value < 0.05),
                        "mean_delta_left_minus_right": round(mean(diffs), 6),
                    }
                )

    return tests


def summarize(input_path: Path) -> dict[str, object]:
    rows = list(csv.DictReader(input_path.open(encoding="utf-8")))
    grouped, grouped_by_rep = index_rows(rows)
    summary_rows = summarize_groups(grouped)
    conclusions = build_conclusions(summary_rows)
    tests = run_statistical_tests(grouped_by_rep)
    return {"summary": summary_rows, "conclusions": conclusions, "hypothesis_tests": tests}


def main() -> None:
    parser = argparse.ArgumentParser(description="Resume o CSV do experimento do pipeline.")
    parser.add_argument("--input", default="data/raw/pipeline_experiment_rq3.csv")
    parser.add_argument("--output", default="data/processed/pipeline_summary_rq3.json")
    args = parser.parse_args()

    result = summarize(Path(args.input))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()