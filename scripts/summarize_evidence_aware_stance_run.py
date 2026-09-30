"""Summarize one evidence-aware stance run and apply the preregistered gate."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


LABELS = ("unrelated", "discuss", "agree", "disagree")
THRESHOLDS = {
    "macro_f1": 0.60,
    "disagree_f1": 0.50,
    "disagree_recall": 0.50,
    "minimum_class_f1": 0.40,
}


def compact_metrics(metrics: dict) -> dict:
    report = metrics["classification_report"]
    confusion = metrics["confusion_matrix"]
    predicted_counts = {
        label: int(sum(row[index] for row in confusion))
        for index, label in enumerate(LABELS)
    }
    return {
        "macro_f1": float(metrics["macro_f1"]),
        "accuracy": float(metrics["accuracy"]),
        "per_class": {
            label: {
                "precision": float(report[label]["precision"]),
                "recall": float(report[label]["recall"]),
                "f1": float(report[label]["f1-score"]),
                "support": int(report[label]["support"]),
                "predicted": predicted_counts[label],
            }
            for label in LABELS
        },
        "confusion_matrix": confusion,
    }


def evaluate_gate(metrics: dict) -> dict:
    values = {
        "macro_f1": metrics["macro_f1"],
        "disagree_f1": metrics["per_class"]["disagree"]["f1"],
        "disagree_recall": metrics["per_class"]["disagree"]["recall"],
        "minimum_class_f1": min(row["f1"] for row in metrics["per_class"].values()),
    }
    criteria = {
        name: {"value": value, "threshold": THRESHOLDS[name], "pass": value >= THRESHOLDS[name]}
        for name, value in values.items()
    }
    criteria["all_classes_predicted"] = {
        "value": all(row["predicted"] > 0 for row in metrics["per_class"].values()),
        "threshold": True,
        "pass": all(row["predicted"] > 0 for row in metrics["per_class"].values()),
    }
    return {"decision": "GO" if all(item["pass"] for item in criteria.values()) else "NO_GO", "criteria": criteria}


def markdown_table(metrics: dict) -> str:
    lines = [
        "| Clase | Precisión | Recall | F1 | Soporte | Predichos |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label in LABELS:
        row = metrics["per_class"][label]
        lines.append(
            f"| {label} | {row['precision']:.4f} | {row['recall']:.4f} | "
            f"{row['f1']:.4f} | {row['support']} | {row['predicted']} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run_dir", type=Path, required=True)
    parser.add_argument("--representation", required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    config_path = run_dir / "best_model" / "serving_config.json"
    history_path = run_dir / "training_history.json"
    if not config_path.exists() or not history_path.exists():
        raise FileNotFoundError("The run is incomplete: serving_config.json or training_history.json is missing")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    history = json.loads(history_path.read_text(encoding="utf-8"))
    validation = compact_metrics(config["validation_metrics"])
    test = compact_metrics(config["test_metrics"])
    gate = evaluate_gate(validation)
    best_epoch = max(history, key=lambda row: row["validation_macro_f1"])["epoch"]

    payload = {
        "status": "COMPLETE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "representation": args.representation,
        "seed": args.seed,
        "run_dir": str(run_dir),
        "best_epoch": best_epoch,
        "development_gate": gate,
        "validation": validation,
        "test_descriptive_not_for_tuning": test,
        "interpretation": (
            "The representation passes the one-seed development gate; replicate and compare representations."
            if gate["decision"] == "GO"
            else "The representation does not pass the one-seed development gate; inspect errors before expanding runs."
        ),
    }
    json_path = run_dir / "run_summary.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    criteria_lines = [
        f"- {name}: {item['value']} (umbral {item['threshold']}) — {'PASS' if item['pass'] else 'FAIL'}"
        for name, item in gate["criteria"].items()
    ]
    markdown = f"""# Resultado del spike de stance

- Representación: `{args.representation}`
- Semilla: `{args.seed}`
- Mejor época: `{best_epoch}`
- Decisión de desarrollo: **{gate['decision']}**

## Criterios de paso (validación)

{chr(10).join(criteria_lines)}

## Validación

- Macro-F1: **{validation['macro_f1']:.4f}**
- Accuracy: **{validation['accuracy']:.4f}**

{markdown_table(validation)}

## Test interno descriptivo (no usado para ajustar)

- Macro-F1: **{test['macro_f1']:.4f}**
- Accuracy: **{test['accuracy']:.4f}**

{markdown_table(test)}

> Este es un resultado de desarrollo con una sola semilla. No sustituye la evaluación prospectiva congelada.
"""
    markdown_path = run_dir / "RUN_SUMMARY.md"
    markdown_path.write_text(markdown, encoding="utf-8")
    print(json.dumps({"decision": gate["decision"], "json": str(json_path), "markdown": str(markdown_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
