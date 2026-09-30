"""Phase-0 diagnostics for the stance V2 decision.

This script never trains or mutates the frozen V1 model. It measures how the
same checkpoint behaves with automatic evidence, complete context, human
evidence spans, title-only, and claim-only inputs on Challenge 04. Challenge 04
is therefore treated as a development stress test for V2, not as V2's final
evaluation set.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from app.ml.evidence_retriever import EvidenceRetriever
from app.ml.stance_classifier import StanceClassifier


LABELS = ["unrelated", "discuss", "agree", "disagree"]
MODEL_DIR = PROJECT / "output" / "stance_es_pe_v1" / "final_model_2026_09_28" / "best_model"
FREEZE_MANIFEST = MODEL_DIR.parent / "model_freeze_manifest.json"
WORKSPACE = Path(r"C:\Users\sdiaz\Documents\Codex\2026-09-14\resolver-o-delimitar-el-componente-de")
CHALLENGE_GOLD = (
    WORKSPACE
    / "outputs"
    / "challenge_04_2026_09_28"
    / "integracion_2026_09_28"
    / "challenge_04_gold.json"
)
CHALLENGE_INTEGRATED = CHALLENGE_GOLD.with_name("challenge_04_integrated.csv")
OUTPUT_DIR = PROJECT / "output" / "stance_es_pe_v2" / "phase0_v1_input_ablation"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_integrated() -> dict[str, dict[str, str]]:
    with CHALLENGE_INTEGRATED.open("r", encoding="utf-8-sig", newline="") as handle:
        return {row["pair_id"]: row for row in csv.DictReader(handle)}


def clean(text: str) -> str:
    return " ".join((text or "").split())


def oracle_span(row: dict, integrated: dict[str, dict[str, str]]) -> str:
    annotation = integrated[row["pair_id"]]
    spans: list[str] = []
    for field in ("jimena_evidence", "salvador_evidence"):
        value = clean(annotation.get(field, ""))
        if value and value.casefold() != "sin evidencia pertinente" and value not in spans:
            spans.append(value)
    return " ".join(spans)


def make_inputs(
    name: str,
    rows: list[dict],
    classifier: StanceClassifier,
    integrated: dict[str, dict[str, str]],
) -> tuple[list[str], list[str], list[dict]]:
    text_a: list[str] = []
    text_b: list[str] = []
    metadata: list[dict] = []
    retriever = EvidenceRetriever()

    for row in rows:
        claim = clean(row["claim"])
        title = clean(row.get("title", ""))
        context = clean(row.get("context", ""))
        span = oracle_span(row, integrated)
        selected_indexes = ""

        if name == "automatic_retrieval":
            selection = retriever.select(
                claim=claim,
                title=title,
                body=context,
                tokenizer=classifier.tokenizer,
                max_length=classifier.serving_config.max_length,
            )
            first, second = claim, selection.context
            selected_indexes = ",".join(map(str, selection.selected_indexes))
        elif name == "full_context_with_title":
            first, second = claim, clean(f"{title} {context}")
        elif name == "full_context_no_title":
            first, second = claim, context
        elif name == "oracle_span_with_title":
            first, second = claim, clean(f"{title} {span}")
        elif name == "oracle_span_no_title":
            first, second = claim, span
        elif name == "title_only":
            first, second = claim, title
        elif name == "claim_only":
            first, second = claim, ""
        elif name == "context_only":
            first, second = "", clean(f"{title} {context}")
        else:
            raise ValueError(f"Representación desconocida: {name}")

        text_a.append(first)
        text_b.append(second)
        metadata.append({
            "input_chars_a": len(first),
            "input_chars_b": len(second),
            "retrieved_indexes": selected_indexes,
        })
    return text_a, text_b, metadata


def predict(
    classifier: StanceClassifier,
    rows: list[dict],
    name: str,
    integrated: dict[str, dict[str, str]],
    batch_size: int = 8,
) -> list[dict]:
    text_a, text_b, input_metadata = make_inputs(name, rows, classifier, integrated)
    predictions: list[dict] = []

    for start in range(0, len(rows), batch_size):
        batch_a = text_a[start : start + batch_size]
        batch_b = text_b[start : start + batch_size]
        encoded = classifier.tokenizer(
            batch_a,
            batch_b,
            return_tensors="pt",
            truncation="only_second",
            max_length=classifier.serving_config.max_length,
            padding=True,
        )
        encoded = {key: value.to(classifier.device) for key, value in encoded.items()}
        with torch.no_grad():
            logits = classifier.model(**encoded).logits
            probabilities = torch.softmax(logits, dim=-1).cpu().numpy()

        for offset, probs in enumerate(probabilities):
            index = start + offset
            row = rows[index]
            predicted_index = int(np.argmax(probs))
            predictions.append({
                "representation": name,
                "pair_id": row["pair_id"],
                "group_id": row["group_id"],
                "gold_label": str(row["gold_label"]).casefold(),
                "prediction": classifier.serving_config.label_names[predicted_index],
                "confidence": float(probs[predicted_index]),
                **{f"p_{label}": float(probs[label_index]) for label_index, label in enumerate(LABELS)},
                **input_metadata[index],
            })
    return predictions


def compute_metrics(rows: list[dict]) -> dict:
    y_true = [row["gold_label"] for row in rows]
    y_pred = [row["prediction"] for row in rows]
    report = classification_report(
        y_true,
        y_pred,
        labels=LABELS,
        output_dict=True,
        zero_division=0,
    )
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row["group_id"]].append(row)
    distinct_predictions = Counter(len({item["prediction"] for item in group}) for group in groups.values())
    correct_per_group = Counter(
        sum(item["gold_label"] == item["prediction"] for item in group)
        for group in groups.values()
    )
    return {
        "n": len(rows),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1_fixed_four": float(
            f1_score(y_true, y_pred, labels=LABELS, average="macro", zero_division=0)
        ),
        "prediction_counts": dict(Counter(y_pred)),
        "per_class_f1": {label: float(report[label]["f1-score"]) for label in LABELS},
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=LABELS).tolist(),
        "distinct_predictions_per_context": {
            str(key): value for key, value in sorted(distinct_predictions.items())
        },
        "correct_predictions_per_context": {
            str(key): value for key, value in sorted(correct_per_group.items())
        },
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    freeze = json.loads(FREEZE_MANIFEST.read_text(encoding="utf-8"))
    expected_hash = freeze["checkpoint"]["files"]["model.safetensors"]["sha256"]
    current_hash = sha256_file(MODEL_DIR / "model.safetensors")
    if current_hash != expected_hash:
        raise SystemExit("El checkpoint V1 no coincide con su manifiesto de congelación.")

    classifier = StanceClassifier(str(MODEL_DIR))
    if not classifier.load():
        raise SystemExit(classifier.load_error or "No se pudo cargar V1.")
    if list(classifier.serving_config.label_names) != LABELS:
        raise SystemExit(f"Orden de etiquetas inesperado: {classifier.serving_config.label_names}")

    rows = json.loads(CHALLENGE_GOLD.read_text(encoding="utf-8"))
    integrated = read_integrated()
    representations = (
        "automatic_retrieval",
        "full_context_with_title",
        "full_context_no_title",
        "oracle_span_with_title",
        "oracle_span_no_title",
        "title_only",
        "claim_only",
        "context_only",
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    all_predictions: list[dict] = []
    results: dict[str, dict] = {}
    for name in representations:
        selected = predict(classifier, rows, name, integrated)
        all_predictions.extend(selected)
        results[name] = compute_metrics(selected)
        print(name, json.dumps(results[name], ensure_ascii=False))

    write_csv(OUTPUT_DIR / "v1_input_ablation_predictions.csv", all_predictions)
    payload = {
        "status": "COMPLETE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "epistemic_role": "V2 development diagnostic; not a new external V1 evaluation",
        "model_dir": str(MODEL_DIR),
        "checkpoint_sha256": current_hash,
        "challenge_gold": str(CHALLENGE_GOLD),
        "challenge_gold_sha256": sha256_file(CHALLENGE_GOLD),
        "representations": results,
    }
    (OUTPUT_DIR / "v1_input_ablation_metrics.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# Stance V2 — diagnóstico de entradas de V1",
        "",
        "Challenge 04 se usa desde este punto únicamente como conjunto de desarrollo para V2.",
        "El checkpoint V1 permanece congelado y no fue reentrenado.",
        "",
        "| Representación | Macro-F1 | Accuracy | F1 Unrelated | F1 Discuss | F1 Agree | F1 Disagree |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in representations:
        result = results[name]
        per_class = result["per_class_f1"]
        lines.append(
            f"| {name} | {result['macro_f1_fixed_four']:.4f} | {result['accuracy']:.4f} "
            f"| {per_class['unrelated']:.4f} | {per_class['discuss']:.4f} "
            f"| {per_class['agree']:.4f} | {per_class['disagree']:.4f} |"
        )
    (OUTPUT_DIR / "V1_INPUT_ABLATION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
