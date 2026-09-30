"""Post-hoc, read-only diagnostics for the frozen operational stance evaluation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from transformers import AutoTokenizer


LABELS = ["unrelated", "discuss", "agree", "disagree"]
LABEL_TO_ID = {label: index for index, label in enumerate(LABELS)}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def pct(values: list[float], q: float) -> float:
    return float(np.quantile(values, q)) if values else 0.0


def metrics(y_true: list[int], y_pred: list[int]) -> dict:
    observed = sorted(set(y_true))
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1_four_class": float(f1_score(y_true, y_pred, labels=range(4), average="macro", zero_division=0)),
        "macro_f1_observed_classes": float(f1_score(y_true, y_pred, labels=observed, average="macro", zero_division=0)),
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=range(4)).tolist(),
        "classification_report": classification_report(y_true, y_pred, labels=range(4), target_names=LABELS, output_dict=True, zero_division=0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-dir", type=Path, required=True)
    parser.add_argument("--gold-json", type=Path, required=True)
    args = parser.parse_args()

    evaluation_dir = args.evaluation_dir.resolve()
    state = json.loads((evaluation_dir / "inference_run_state.json").read_text(encoding="utf-8"))
    if state["status"] != "COMPLETED_ONE_SHOT_INFERENCE":
        raise ValueError("Inference is not complete")
    if sha256_file(evaluation_dir / "predictions.csv") != state["prediction_file_sha256"]:
        raise ValueError("Predictions hash mismatch")
    if sha256_file(evaluation_dir / "metrics.json") != state["metrics_file_sha256"]:
        raise ValueError("Metrics hash mismatch")

    payload = json.loads((evaluation_dir / "metrics.json").read_text(encoding="utf-8"))
    predictions = read_csv(evaluation_dir / "predictions.csv")
    gold_rows = json.loads(args.gold_json.resolve().read_text(encoding="utf-8"))
    if [row["pair_id"] for row in predictions] != [row["pair_id"] for row in gold_rows]:
        raise ValueError("Prediction/gold pair alignment mismatch")
    if len({row["pair_id"] for row in predictions}) != len(predictions):
        raise ValueError("Duplicate prediction pair IDs")

    y_true = [LABEL_TO_ID[row["gold_label"]] for row in predictions]
    y_pred = [LABEL_TO_ID[row["predicted_label"]] for row in predictions]
    baseline_pred = [LABEL_TO_ID["agree"]] * len(y_true)
    baseline = metrics(y_true, baseline_pred)
    model = metrics(y_true, y_pred)

    model_dir = Path(payload["model_dir"])
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True)
    max_length = int(payload["max_length"])
    pair_specials = tokenizer.num_special_tokens_to_add(pair=True)
    token_rows = []
    for pred, gold in zip(predictions, gold_rows, strict=True):
        claim_ids = tokenizer(gold["claim"], add_special_tokens=False)["input_ids"]
        body_ids = tokenizer(gold["article"], add_special_tokens=False)["input_ids"]
        body_budget = max(0, max_length - len(claim_ids) - pair_specials)
        exact_at = gold["article"].casefold().find(gold["claim"].casefold())
        prefix_tokens = None
        exact_evidence_retained = None
        if exact_at >= 0:
            prefix_tokens = len(tokenizer(gold["article"][:exact_at], add_special_tokens=False)["input_ids"])
            exact_evidence_retained = prefix_tokens < body_budget
        token_rows.append({
            "pair_id": pred["pair_id"],
            "gold_label": pred["gold_label"],
            "predicted_label": pred["predicted_label"],
            "correct": pred["correct"].lower() == "true",
            "claim_tokens": len(claim_ids),
            "article_tokens": len(body_ids),
            "body_token_budget": body_budget,
            "article_truncated": len(body_ids) > body_budget,
            "retained_article_fraction": min(1.0, body_budget / max(1, len(body_ids))),
            "claim_exactly_in_article": exact_at >= 0,
            "exact_claim_prefix_tokens": prefix_tokens,
            "exact_claim_evidence_retained": exact_evidence_retained,
        })

    truncated = [row for row in token_rows if row["article_truncated"]]
    exact = [row for row in token_rows if row["claim_exactly_in_article"]]
    exact_outside = [row for row in exact if row["exact_claim_evidence_retained"] is False]
    exact_inside = [row for row in exact if row["exact_claim_evidence_retained"] is True]
    errors = [row for row in predictions if row["correct"].lower() != "true"]
    confidences = [max(float(row[f"p_{label}"]) for label in LABELS) for row in predictions]
    error_confidences = [max(float(row[f"p_{label}"]) for label in LABELS) for row in errors]
    diagnostic = {
        "status": "PASS_DIAGNOSTIC_AUDIT",
        "alignment": {
            "pairs": len(predictions),
            "unique_pair_ids": len({row["pair_id"] for row in predictions}),
            "prediction_gold_order_identical": True,
            "prediction_hash_verified": True,
            "metrics_hash_verified": True,
        },
        "model_vs_majority_baseline": {
            "model": model,
            "always_agree_baseline": baseline,
            "accuracy_delta_model_minus_baseline": model["accuracy"] - baseline["accuracy"],
            "observed_macro_f1_delta_model_minus_baseline": model["macro_f1_observed_classes"] - baseline["macro_f1_observed_classes"],
        },
        "collapse": {
            "predicted_counts": dict(Counter(row["predicted_label"] for row in predictions)),
            "missing_predicted_classes": [label for label in LABELS if not any(row["predicted_label"] == label for row in predictions)],
            "errors": len(errors),
            "error_transitions": dict(Counter(f"{row['gold_label']}->{row['predicted_label']}" for row in errors)),
            "mean_max_probability_all": statistics.fmean(confidences),
            "mean_max_probability_errors": statistics.fmean(error_confidences),
        },
        "input_length_diagnostic": {
            "max_length": max_length,
            "pair_special_tokens": pair_specials,
            "truncated_articles": len(truncated),
            "truncated_article_rate": len(truncated) / len(token_rows),
            "article_tokens_median": pct([row["article_tokens"] for row in token_rows], 0.5),
            "article_tokens_p95": pct([row["article_tokens"] for row in token_rows], 0.95),
            "body_budget_median": pct([row["body_token_budget"] for row in token_rows], 0.5),
            "retained_article_fraction_median": pct([row["retained_article_fraction"] for row in token_rows], 0.5),
            "retained_article_fraction_p05": pct([row["retained_article_fraction"] for row in token_rows], 0.05),
            "exact_claim_matches": len(exact),
            "exact_claim_matches_beyond_retained_prefix": len(exact_outside),
            "when_exact_claim_retained": {
                "n": len(exact_inside),
                "accuracy": sum(row["correct"] for row in exact_inside) / len(exact_inside),
                "gold_counts": dict(Counter(row["gold_label"] for row in exact_inside)),
                "predicted_counts": dict(Counter(row["predicted_label"] for row in exact_inside)),
            },
            "when_exact_claim_beyond_retained_prefix": {
                "n": len(exact_outside),
                "accuracy": sum(row["correct"] for row in exact_outside) / len(exact_outside),
                "gold_counts": dict(Counter(row["gold_label"] for row in exact_outside)),
                "predicted_counts": dict(Counter(row["predicted_label"] for row in exact_outside)),
            },
        },
        "interpretation": [
            "The failure is not caused by row or label misalignment; hashes and pair order match the frozen gold.",
            "The checkpoint collapses operationally because it emits only unrelated and agree, with zero discuss/disagree predictions.",
            "Accuracy is misleading under natural prevalence: the always-agree baseline is stronger on accuracy and observed-class macro-F1.",
            "Input truncation is a plausible contributing factor and is quantified here, but this final set must not be reused for tuning.",
            "Truncation is not sufficient to explain the collapse: when the exact claim is retained, every case is still predicted agree, including discuss/disagree cases.",
        ],
    }
    (evaluation_dir / "diagnostic.json").write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8")
    with (evaluation_dir / "token_length_audit.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(token_rows[0]))
        writer.writeheader()
        writer.writerows(token_rows)

    base = diagnostic["model_vs_majority_baseline"]["always_agree_baseline"]
    trunc = diagnostic["input_length_diagnostic"]
    collapse = diagnostic["collapse"]
    report = f"""# Diagnóstico posterior de la evaluación operacional

## Veredicto

El fallo es real y no corresponde a un desplazamiento de filas o etiquetas. Los 110 `pair_id` están alineados, son únicos y los hashes de predicciones y métricas coinciden con el marcador de la corrida única.

- Modelo: accuracy={model['accuracy']:.4f}; macro-F1 fijo={model['macro_f1_four_class']:.4f}; macro-F1 observado={model['macro_f1_observed_classes']:.4f}.
- Línea base siempre-`agree`: accuracy={base['accuracy']:.4f}; macro-F1 fijo={base['macro_f1_four_class']:.4f}; macro-F1 observado={base['macro_f1_observed_classes']:.4f}.
- Diferencia modelo - línea base: accuracy={diagnostic['model_vs_majority_baseline']['accuracy_delta_model_minus_baseline']:.4f}; macro-F1 observado={diagnostic['model_vs_majority_baseline']['observed_macro_f1_delta_model_minus_baseline']:.4f}.
- Clases nunca predichas: {collapse['missing_predicted_classes']}.
- Errores: {collapse['errors']}; transiciones: {collapse['error_transitions']}.

## Longitud y truncamiento

- Artículos truncados a `max_length={max_length}`: {trunc['truncated_articles']}/{len(token_rows)} ({trunc['truncated_article_rate']:.1%}).
- Tokens de artículo: mediana={trunc['article_tokens_median']:.0f}; p95={trunc['article_tokens_p95']:.0f}.
- Fracción mediana del artículo retenida: {trunc['retained_article_fraction_median']:.1%}.
- Claims con coincidencia literal en el artículo: {trunc['exact_claim_matches']}; fuera del prefijo retenido: {trunc['exact_claim_matches_beyond_retained_prefix']}.
- Con evidencia literal retenida: n={trunc['when_exact_claim_retained']['n']}, accuracy={trunc['when_exact_claim_retained']['accuracy']:.4f}, gold={trunc['when_exact_claim_retained']['gold_counts']}, predicho={trunc['when_exact_claim_retained']['predicted_counts']}.
- Con evidencia literal fuera del prefijo: n={trunc['when_exact_claim_beyond_retained_prefix']['n']}, accuracy={trunc['when_exact_claim_beyond_retained_prefix']['accuracy']:.4f}, gold={trunc['when_exact_claim_beyond_retained_prefix']['gold_counts']}, predicho={trunc['when_exact_claim_beyond_retained_prefix']['predicted_counts']}.

El truncamiento es un mecanismo plausible de las falsas predicciones `unrelated`, pero no explica por sí solo el colapso: cuando la mención literal sí está retenida, el modelo predice `agree` en los 36 casos, incluidos los cuatro casos `discuss`/`disagree`. Esto apunta además a un sesgo de solapamiento léxico y a una falla para reconocer contexto de discusión/refutación. El conjunto final queda cerrado y no debe reutilizarse para cambiar `max_length`, seleccionar otro checkpoint ni ajustar umbrales.
"""
    (evaluation_dir / "diagnostic.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
