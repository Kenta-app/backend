"""
Fit recommended fake-news thresholds from a labeled calibration CSV.

Expected columns:
    - risk score column, default: analysis_risk_score
    - gold label column, default: manual_gold

Accepted labels:
    true/verdadero/real
    false/falso/fake
    indeterminate/unclear/skip (ignored)
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path


TRUE_LABELS = {"true", "verdadero", "real", "1"}
FALSE_LABELS = {"false", "falso", "fake", "0"}
SKIP_LABELS = {"", "skip", "unclear", "indeterminate", "indeterminado", "na", "n/a"}


@dataclass(frozen=True)
class CalibrationRow:
    risk_score: float
    gold_label: str


@dataclass(frozen=True)
class TriageMetrics:
    low_threshold: float
    high_threshold: float
    false_precision: float
    false_recall: float
    true_precision: float
    true_recall: float
    macro_f1: float
    coverage: float
    decided_accuracy: float
    predicted_false: int
    predicted_true: int
    undecided: int


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fit fake-news thresholds from a labeled CSV.")
    parser.add_argument("--input", required=True, help="Calibration CSV.")
    parser.add_argument("--label-column", default="manual_gold")
    parser.add_argument("--risk-column", default="analysis_risk_score")
    parser.add_argument("--min-false-precision", type=float, default=0.90)
    parser.add_argument("--min-true-precision", type=float, default=0.80)
    parser.add_argument("--top-k", type=int, default=10, help="How many candidate configurations to print.")
    return parser


def normalize_label(value: str) -> str | None:
    normalized = (value or "").strip().lower()
    if normalized in TRUE_LABELS:
        return "true"
    if normalized in FALSE_LABELS:
        return "false"
    if normalized in SKIP_LABELS:
        return None
    return None


def safe_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_rows(path: str, *, label_column: str, risk_column: str) -> list[CalibrationRow]:
    rows: list[CalibrationRow] = []
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            label = normalize_label(raw.get(label_column, ""))
            risk_score = safe_float(raw.get(risk_column, ""))
            if label is None or risk_score is None:
                continue
            rows.append(CalibrationRow(risk_score=risk_score, gold_label=label))
    return rows


def f1(precision: float, recall: float) -> float:
    if precision <= 0.0 or recall <= 0.0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def evaluate_triage(rows: list[CalibrationRow], low: float, high: float) -> TriageMetrics:
    true_total = sum(1 for row in rows if row.gold_label == "true")
    false_total = sum(1 for row in rows if row.gold_label == "false")

    pred_true = pred_false = undecided = 0
    tp_true = tp_false = correct_decided = 0

    for row in rows:
        if row.risk_score <= low:
            pred_true += 1
            if row.gold_label == "true":
                tp_true += 1
                correct_decided += 1
        elif row.risk_score >= high:
            pred_false += 1
            if row.gold_label == "false":
                tp_false += 1
                correct_decided += 1
        else:
            undecided += 1

    false_precision = tp_false / pred_false if pred_false else 0.0
    false_recall = tp_false / false_total if false_total else 0.0
    true_precision = tp_true / pred_true if pred_true else 0.0
    true_recall = tp_true / true_total if true_total else 0.0
    macro_f1 = (f1(false_precision, false_recall) + f1(true_precision, true_recall)) / 2.0
    decided = pred_true + pred_false
    coverage = decided / len(rows) if rows else 0.0
    decided_accuracy = correct_decided / decided if decided else 0.0

    return TriageMetrics(
        low_threshold=low,
        high_threshold=high,
        false_precision=false_precision,
        false_recall=false_recall,
        true_precision=true_precision,
        true_recall=true_recall,
        macro_f1=macro_f1,
        coverage=coverage,
        decided_accuracy=decided_accuracy,
        predicted_false=pred_false,
        predicted_true=pred_true,
        undecided=undecided,
    )


def fit_thresholds(
    rows: list[CalibrationRow],
    *,
    min_false_precision: float,
    min_true_precision: float,
) -> tuple[TriageMetrics | None, list[TriageMetrics]]:
    candidates = sorted({0.0, 1.0, *[round(row.risk_score, 6) for row in rows]})
    scored: list[TriageMetrics] = []
    for low in candidates:
        for high in candidates:
            if low >= high:
                continue
            metrics = evaluate_triage(rows, low, high)
            scored.append(metrics)

    scored.sort(
        key=lambda item: (
            item.coverage,
            item.macro_f1,
            item.decided_accuracy,
            item.false_precision + item.true_precision,
        ),
        reverse=True,
    )

    for metrics in scored:
        if (
            metrics.false_precision >= min_false_precision
            and metrics.true_precision >= min_true_precision
            and metrics.predicted_false > 0
            and metrics.predicted_true > 0
        ):
            return metrics, scored

    return None, scored


def print_metrics(label: str, metrics: TriageMetrics) -> None:
    print(label)
    print(f"  low_threshold   : {metrics.low_threshold:.4f}")
    print(f"  high_threshold  : {metrics.high_threshold:.4f}")
    print(f"  false_precision : {metrics.false_precision:.4f}")
    print(f"  false_recall    : {metrics.false_recall:.4f}")
    print(f"  true_precision  : {metrics.true_precision:.4f}")
    print(f"  true_recall     : {metrics.true_recall:.4f}")
    print(f"  macro_f1        : {metrics.macro_f1:.4f}")
    print(f"  coverage        : {metrics.coverage:.4f}")
    print(f"  decided_accuracy: {metrics.decided_accuracy:.4f}")
    print(
        f"  counts          : predicted_false={metrics.predicted_false} "
        f"predicted_true={metrics.predicted_true} undecided={metrics.undecided}"
    )


def main() -> int:
    args = build_parser().parse_args()
    rows = load_rows(
        args.input,
        label_column=args.label_column,
        risk_column=args.risk_column,
    )
    if not rows:
        print("No usable labeled rows were found.")
        return 1

    best, scored = fit_thresholds(
        rows,
        min_false_precision=args.min_false_precision,
        min_true_precision=args.min_true_precision,
    )

    print(f"Loaded {len(rows)} labeled rows from {args.input}")
    print("")

    if best is not None:
        print_metrics("Recommended triage thresholds", best)
        print("")
        print("Suggested environment variables")
        print(f"  FAKENEWS_ARTICLE_LOW_THRESHOLD={best.low_threshold:.4f}")
        print(f"  FAKENEWS_ARTICLE_HIGH_THRESHOLD={best.high_threshold:.4f}")
        print("")
    else:
        print("No threshold pair satisfied the requested precision constraints.")
        print("Lower the constraints or label more calibration examples.")
        print("")

    print("Top candidate configurations")
    for metrics in scored[: max(args.top_k, 1)]:
        print(
            f"  low={metrics.low_threshold:.4f} high={metrics.high_threshold:.4f} "
            f"coverage={metrics.coverage:.4f} macro_f1={metrics.macro_f1:.4f} "
            f"false_precision={metrics.false_precision:.4f} true_precision={metrics.true_precision:.4f}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
