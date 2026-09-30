"""Benchmark a Spanish NLI checkpoint on the related portion of Challenge 04.

The benchmark is deliberately zero-shot and development-only. It answers a
single feasibility question: does an encoder already adapted to Spanish NLI
separate entailment, neutral discussion, and contradiction better than the V1
stance checkpoint before any new annotation or fine-tuning?
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from transformers import AutoModelForSequenceClassification, AutoTokenizer


DEFAULT_MODEL = "Recognai/bert-base-spanish-wwm-cased-xnli"
WORKSPACE = Path(r"C:\Users\sdiaz\Documents\Codex\2026-09-14\resolver-o-delimitar-el-componente-de")
CHALLENGE_GOLD = (
    WORKSPACE
    / "outputs"
    / "challenge_04_2026_09_28"
    / "integracion_2026_09_28"
    / "challenge_04_gold.json"
)
CHALLENGE_INTEGRATED = CHALLENGE_GOLD.with_name("challenge_04_integrated.csv")
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "output" / "stance_es_pe_v2" / "phase0_nli_zero_shot"
STANCE_TO_NLI = {
    "agree": "entailment",
    "discuss": "neutral",
    "disagree": "contradiction",
}
NLI_LABELS = ["contradiction", "neutral", "entailment"]


def clean(text: str) -> str:
    return " ".join((text or "").split())


def load_integrated() -> dict[str, dict[str, str]]:
    with CHALLENGE_INTEGRATED.open("r", encoding="utf-8-sig", newline="") as handle:
        return {row["pair_id"]: row for row in csv.DictReader(handle)}


def oracle_span(pair_id: str, integrated: dict[str, dict[str, str]]) -> str:
    row = integrated[pair_id]
    spans: list[str] = []
    for field in ("jimena_evidence", "salvador_evidence"):
        value = clean(row.get(field, ""))
        if value and value.casefold() != "sin evidencia pertinente" and value not in spans:
            spans.append(value)
    return " ".join(spans)


def resolve_label_map(model) -> dict[int, str]:
    raw = {int(key): str(value).casefold() for key, value in model.config.id2label.items()}
    aliases = {
        "contradiction": "contradiction",
        "contradict": "contradiction",
        "neutral": "neutral",
        "entailment": "entailment",
        "entail": "entailment",
    }
    resolved: dict[int, str] = {}
    for index, value in raw.items():
        for token, label in aliases.items():
            if token in value:
                resolved[index] = label
                break
    if set(resolved.values()) == set(NLI_LABELS):
        return resolved

    # Recognai's published XNLI training script remaps the Spanish XNLI labels
    # to contradiction=0, neutral=1, entailment=2 for zero-shot compatibility.
    if model.config.name_or_path.casefold().rstrip("/") == DEFAULT_MODEL.casefold():
        return {0: "contradiction", 1: "neutral", 2: "entailment"}
    raise ValueError(f"No se pudo resolver el orden NLI desde id2label={raw}")


def build_premise(row: dict, representation: str, integrated: dict[str, dict[str, str]]) -> str:
    title = clean(row.get("title", ""))
    context = clean(row.get("context", ""))
    if representation == "full_context":
        return context
    if representation == "title_plus_context":
        return clean(f"{title} {context}")
    if representation == "oracle_span":
        return oracle_span(row["pair_id"], integrated)
    if representation == "title_plus_oracle_span":
        return clean(f"{title} {oracle_span(row['pair_id'], integrated)}")
    raise ValueError(representation)


def predict_representation(
    *,
    model,
    tokenizer,
    device: torch.device,
    label_map: dict[int, str],
    rows: list[dict],
    representation: str,
    integrated: dict[str, dict[str, str]],
    batch_size: int,
    max_length: int,
) -> list[dict]:
    outputs: list[dict] = []
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        premises = [build_premise(row, representation, integrated) for row in batch]
        hypotheses = [clean(row["claim"]) for row in batch]
        encoded = tokenizer(
            premises,
            hypotheses,
            return_tensors="pt",
            padding=True,
            truncation="only_first",
            max_length=max_length,
        )
        encoded = {key: value.to(device) for key, value in encoded.items()}
        with torch.no_grad():
            logits = model(**encoded).logits
            probabilities = torch.softmax(logits, dim=-1).cpu().numpy()
        for row, premise, probs in zip(batch, premises, probabilities):
            best_index = int(np.argmax(probs))
            outputs.append({
                "representation": representation,
                "pair_id": row["pair_id"],
                "group_id": row["group_id"],
                "gold_stance": str(row["gold_label"]).casefold(),
                "gold_nli": STANCE_TO_NLI[str(row["gold_label"]).casefold()],
                "prediction_nli": label_map[best_index],
                "confidence": float(probs[best_index]),
                "p_contradiction": float(probs[next(i for i, label in label_map.items() if label == "contradiction")]),
                "p_neutral": float(probs[next(i for i, label in label_map.items() if label == "neutral")]),
                "p_entailment": float(probs[next(i for i, label in label_map.items() if label == "entailment")]),
                "premise_chars": len(premise),
            })
    return outputs


def metrics(rows: list[dict]) -> dict:
    y_true = [row["gold_nli"] for row in rows]
    y_pred = [row["prediction_nli"] for row in rows]
    report = classification_report(
        y_true, y_pred, labels=NLI_LABELS, output_dict=True, zero_division=0
    )
    return {
        "n_related": len(rows),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1_three_way": float(
            f1_score(y_true, y_pred, labels=NLI_LABELS, average="macro", zero_division=0)
        ),
        "per_class_f1": {label: float(report[label]["f1-score"]) for label in NLI_LABELS},
        "prediction_counts": dict(Counter(y_pred)),
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=NLI_LABELS).tolist(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--output_dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--batch_size", type=int, default=8)
    parser.add_argument("--max_length", type=int, default=384)
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForSequenceClassification.from_pretrained(args.model).to(device)
    model.eval()
    label_map = resolve_label_map(model)

    all_rows = json.loads(CHALLENGE_GOLD.read_text(encoding="utf-8"))
    rows = [row for row in all_rows if str(row["gold_label"]).casefold() in STANCE_TO_NLI]
    integrated = load_integrated()
    representations = (
        "full_context",
        "title_plus_context",
        "oracle_span",
        "title_plus_oracle_span",
    )
    predictions: list[dict] = []
    results: dict[str, dict] = {}
    for representation in representations:
        selected = predict_representation(
            model=model,
            tokenizer=tokenizer,
            device=device,
            label_map=label_map,
            rows=rows,
            representation=representation,
            integrated=integrated,
            batch_size=args.batch_size,
            max_length=args.max_length,
        )
        predictions.extend(selected)
        results[representation] = metrics(selected)
        print(representation, json.dumps(results[representation], ensure_ascii=False))

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "nli_zero_shot_predictions.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(predictions[0]))
        writer.writeheader()
        writer.writerows(predictions)

    payload = {
        "status": "COMPLETE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "epistemic_role": "V2 development-only zero-shot feasibility diagnostic",
        "model": args.model,
        "device": str(device),
        "label_map": label_map,
        "excludes_unrelated": True,
        "reason_unrelated_excluded": (
            "Three-way NLI maps agree/discuss/disagree to entailment/neutral/contradiction; "
            "unrelated requires a separate relevance stage."
        ),
        "representations": results,
    }
    (output_dir / "nli_zero_shot_metrics.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# Stance V2 — factibilidad zero-shot NLI",
        "",
        f"Modelo: `{args.model}`",
        "",
        "Se evalúan únicamente los 60 casos relacionados. `Unrelated` necesita una etapa de relevancia separada.",
        "",
        "| Representación | Macro-F1 NLI | Accuracy | F1 contradicción | F1 neutral | F1 implicación |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for representation in representations:
        result = results[representation]
        per_class = result["per_class_f1"]
        lines.append(
            f"| {representation} | {result['macro_f1_three_way']:.4f} | {result['accuracy']:.4f} "
            f"| {per_class['contradiction']:.4f} | {per_class['neutral']:.4f} "
            f"| {per_class['entailment']:.4f} |"
        )
    (output_dir / "NLI_ZERO_SHOT_FEASIBILITY.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
