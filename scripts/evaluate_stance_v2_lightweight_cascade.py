"""Evaluate the final bounded V2 feasibility candidate.

Stage A is a lightweight related/unrelated logistic classifier over relational
similarity features and frozen Spanish-XNLI probabilities. Stage B maps the
unchanged NLI outputs to disagree/discuss/agree. Five-fold grouped evaluation
on Challenge 04 keeps every validation context out of Stage-A training.

This is a development diagnostic, not a final or external V2 evaluation.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.metrics.pairwise import paired_cosine_distances
from transformers import AutoModelForSequenceClassification, AutoTokenizer


LABELS = ["unrelated", "discuss", "agree", "disagree"]
NLI_TO_STANCE = {
    "contradiction": "disagree",
    "neutral": "discuss",
    "entailment": "agree",
}
DEFAULT_MODEL = "Recognai/bert-base-spanish-wwm-cased-xnli"
PROJECT = Path(__file__).resolve().parents[1]
V1_TRAINING = PROJECT / "output" / "stance_es_pe_v1" / "final_model_2026_09_28" / "training_data"
WORKSPACE = Path(r"C:\Users\sdiaz\Documents\Codex\2026-09-14\resolver-o-delimitar-el-componente-de")
CHALLENGE_GOLD = (
    WORKSPACE
    / "outputs"
    / "challenge_04_2026_09_28"
    / "integracion_2026_09_28"
    / "challenge_04_gold.json"
)
DEFAULT_OUTPUT = PROJECT / "output" / "stance_es_pe_v2" / "phase0_lightweight_cascade"


def clean(text: str) -> str:
    return " ".join((text or "").split())


def normalized_tokens(text: str) -> set[str]:
    value = unicodedata.normalize("NFKD", text or "").casefold()
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    return {token for token in re.findall(r"\b\w+\b", value) if len(token) > 2}


def numbers(text: str) -> set[str]:
    return set(re.findall(r"\b\d+(?:[.,]\d+)?%?\b", text or ""))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_rows() -> tuple[list[dict], list[dict]]:
    stances = read_csv(V1_TRAINING / "development_all_stances.csv")
    bodies = {
        row["Body ID"]: row["articleBody"]
        for row in read_csv(V1_TRAINING / "development_all_bodies.csv")
    }
    metadata = {
        row["Body ID"]: row
        for row in read_csv(V1_TRAINING / "development_all_metadata.csv")
    }
    v1_rows = []
    for row in stances:
        body_id = row["Body ID"]
        v1_rows.append({
            "pair_id": metadata[body_id]["pair_id"],
            "group_id": metadata[body_id]["group_id"],
            "claim": clean(row["Headline"]),
            "context": clean(bodies[body_id]),
            "label": row["Stance"].casefold(),
            "origin": "v1_development",
        })

    challenge_raw = json.loads(CHALLENGE_GOLD.read_text(encoding="utf-8"))
    challenge_rows = [
        {
            "pair_id": row["pair_id"],
            "group_id": row["group_id"],
            "claim": clean(row["claim"]),
            "context": clean(f"{row.get('title', '')} {row.get('context', '')}"),
            "label": str(row["gold_label"]).casefold(),
            "origin": "challenge_04_contrastive_development",
        }
        for row in challenge_raw
    ]
    return v1_rows, challenge_rows


def build_folds(groups: list[str], seed: int) -> list[list[str]]:
    shuffled = sorted(groups)
    random.Random(seed).shuffle(shuffled)
    folds = [[] for _ in range(5)]
    for index, group in enumerate(shuffled):
        folds[index % 5].append(group)
    return [sorted(fold) for fold in folds]


def resolve_label_map(model) -> dict[int, str]:
    raw = {int(key): str(value).casefold() for key, value in model.config.id2label.items()}
    resolved = {}
    for index, value in raw.items():
        if "contrad" in value:
            resolved[index] = "contradiction"
        elif "neutral" in value:
            resolved[index] = "neutral"
        elif "entail" in value:
            resolved[index] = "entailment"
    if set(resolved.values()) == set(NLI_TO_STANCE):
        return resolved
    if model.config.name_or_path.casefold().rstrip("/") == DEFAULT_MODEL.casefold():
        return {0: "contradiction", 1: "neutral", 2: "entailment"}
    raise ValueError(f"No se pudo resolver id2label={raw}")


def infer_nli(rows: list[dict], model_name: str, batch_size: int, max_length: int) -> None:
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(model_name)
    label_map = resolve_label_map(model)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device).eval()
    label_indexes = {label: index for index, label in label_map.items()}
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        encoded = tokenizer(
            [row["context"] for row in batch],
            [row["claim"] for row in batch],
            return_tensors="pt",
            padding=True,
            truncation="only_first",
            max_length=max_length,
        )
        encoded = {key: value.to(device) for key, value in encoded.items()}
        with torch.no_grad():
            probabilities = torch.softmax(model(**encoded).logits, dim=-1).cpu().numpy()
        for row, probs in zip(batch, probabilities):
            row["p_contradiction"] = float(probs[label_indexes["contradiction"]])
            row["p_neutral"] = float(probs[label_indexes["neutral"]])
            row["p_entailment"] = float(probs[label_indexes["entailment"]])
            row["nli_prediction"] = label_map[int(np.argmax(probs))]


def scalar_features(rows: list[dict]) -> np.ndarray:
    output = []
    for row in rows:
        claim_tokens = normalized_tokens(row["claim"])
        context_tokens = normalized_tokens(row["context"])
        overlap = len(claim_tokens & context_tokens)
        union = len(claim_tokens | context_tokens)
        claim_numbers = numbers(row["claim"])
        context_numbers = numbers(row["context"])
        probs = np.asarray([
            row["p_contradiction"], row["p_neutral"], row["p_entailment"]
        ], dtype=float)
        entropy = -float(sum(value * math.log(max(value, 1e-12)) for value in probs))
        ordered = np.sort(probs)
        output.append([
            overlap / max(1, union),
            overlap / max(1, len(claim_tokens)),
            overlap / max(1, len(context_tokens)),
            min(len(claim_tokens), len(context_tokens)) / max(1, max(len(claim_tokens), len(context_tokens))),
            len(claim_numbers & context_numbers) / max(1, len(claim_numbers)),
            1.0 if claim_numbers and claim_numbers <= context_numbers else 0.0,
            row["p_contradiction"],
            row["p_neutral"],
            row["p_entailment"],
            entropy,
            float(ordered[-1]),
            float(ordered[-1] - ordered[-2]),
        ])
    return np.asarray(output, dtype=float)


def tfidf_pair_cosines(train_rows: list[dict], eval_rows: list[dict], analyzer: str) -> tuple[np.ndarray, np.ndarray]:
    if analyzer == "word":
        vectorizer = TfidfVectorizer(
            strip_accents="unicode", ngram_range=(1, 2), min_df=1, sublinear_tf=True
        )
    else:
        vectorizer = TfidfVectorizer(
            strip_accents="unicode", analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True
        )
    vectorizer.fit([text for row in train_rows for text in (row["claim"], row["context"])])

    def cosines(rows: list[dict]) -> np.ndarray:
        claims = vectorizer.transform([row["claim"] for row in rows])
        contexts = vectorizer.transform([row["context"] for row in rows])
        return (1.0 - paired_cosine_distances(claims, contexts)).reshape(-1, 1)

    return cosines(train_rows), cosines(eval_rows)


def build_features(train_rows: list[dict], eval_rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    train_word, eval_word = tfidf_pair_cosines(train_rows, eval_rows, "word")
    train_char, eval_char = tfidf_pair_cosines(train_rows, eval_rows, "char")
    train_x = np.hstack([scalar_features(train_rows), train_word, train_char])
    eval_x = np.hstack([scalar_features(eval_rows), eval_word, eval_char])
    return train_x, eval_x


def compute_metrics(rows: list[dict]) -> dict:
    y_true = [row["gold_label"] for row in rows]
    y_pred = [row["prediction"] for row in rows]
    report = classification_report(
        y_true, y_pred, labels=LABELS, output_dict=True, zero_division=0
    )
    return {
        "n": len(rows),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1_fixed_four": float(
            f1_score(y_true, y_pred, labels=LABELS, average="macro", zero_division=0)
        ),
        "prediction_counts": dict(Counter(y_pred)),
        "per_class": {
            label: {
                "precision": float(report[label]["precision"]),
                "recall": float(report[label]["recall"]),
                "f1": float(report[label]["f1-score"]),
                "support": int(report[label]["support"]),
            }
            for label in LABELS
        },
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=LABELS).tolist(),
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--output_dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--batch_size", type=int, default=8)
    parser.add_argument("--max_length", type=int, default=384)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    v1_rows, challenge_rows = load_rows()
    all_rows = [*v1_rows, *challenge_rows]
    infer_nli(all_rows, args.model, args.batch_size, args.max_length)
    folds = build_folds(sorted({row["group_id"] for row in challenge_rows}), args.seed)
    predictions = []
    fold_metrics = []

    for fold_index, validation_groups in enumerate(folds, start=1):
        validation_set = set(validation_groups)
        challenge_train = [row for row in challenge_rows if row["group_id"] not in validation_set]
        validation_rows = [row for row in challenge_rows if row["group_id"] in validation_set]
        train_rows = [*v1_rows, *challenge_train]
        train_x, validation_x = build_features(train_rows, validation_rows)
        train_y = np.asarray([int(row["label"] != "unrelated") for row in train_rows])
        classifier = LogisticRegression(
            class_weight="balanced", max_iter=3000, random_state=args.seed + fold_index
        )
        classifier.fit(train_x, train_y)
        related_probabilities = classifier.predict_proba(validation_x)[:, 1]
        fold_predictions = []
        for row, related_probability in zip(validation_rows, related_probabilities):
            if related_probability < 0.5:
                prediction = "unrelated"
            else:
                prediction = NLI_TO_STANCE[row["nli_prediction"]]
            fold_predictions.append({
                "fold": fold_index,
                "pair_id": row["pair_id"],
                "group_id": row["group_id"],
                "gold_label": row["label"],
                "prediction": prediction,
                "related_probability": float(related_probability),
                "nli_prediction": row["nli_prediction"],
                "p_contradiction": row["p_contradiction"],
                "p_neutral": row["p_neutral"],
                "p_entailment": row["p_entailment"],
            })
        selected_metrics = compute_metrics(fold_predictions)
        fold_metrics.append({
            "fold": fold_index,
            "validation_groups": validation_groups,
            "metrics": selected_metrics,
            "relevance_coefficients": classifier.coef_[0].tolist(),
            "relevance_intercept": float(classifier.intercept_[0]),
        })
        predictions.extend(fold_predictions)
        print(
            f"fold={fold_index} macro_f1={selected_metrics['macro_f1_fixed_four']:.4f} "
            f"accuracy={selected_metrics['accuracy']:.4f}", flush=True
        )

    predictions.sort(key=lambda row: row["pair_id"])
    aggregate = compute_metrics(predictions)
    gate = {
        "macro_f1_at_least_0_60": aggregate["macro_f1_fixed_four"] >= 0.60,
        "disagree_f1_at_least_0_50": aggregate["per_class"]["disagree"]["f1"] >= 0.50,
        "disagree_recall_at_least_0_50": aggregate["per_class"]["disagree"]["recall"] >= 0.50,
        "minimum_class_f1_at_least_0_40": min(
            result["f1"] for result in aggregate["per_class"].values()
        ) >= 0.40,
        "all_four_classes_predicted": set(aggregate["prediction_counts"]) == set(LABELS),
    }
    gate["development_go"] = all(gate.values())
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "cascade_oof_predictions.csv", predictions)
    payload = {
        "status": "COMPLETE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "epistemic_role": "final bounded V2 development feasibility test",
        "model": args.model,
        "design": {
            "stage_a": "balanced logistic regression over relational similarity and frozen NLI probabilities",
            "stage_b": "frozen Spanish XNLI argmax mapped to disagree/discuss/agree",
            "threshold": 0.5,
            "folds": 5,
            "grouping": "Challenge-04 context",
        },
        "fold_metrics": fold_metrics,
        "aggregate_out_of_fold_metrics": aggregate,
        "development_gate": gate,
    }
    (output_dir / "cascade_metrics.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Stance V2 — cascada ligera",
        "",
        f"- Macro-F1 out-of-fold: **{aggregate['macro_f1_fixed_four']:.4f}**.",
        f"- Accuracy: **{aggregate['accuracy']:.4f}**.",
        f"- Decisión de desarrollo: **{'GO' if gate['development_go'] else 'NO GO'}**.",
        "",
        "| Clase | Precisión | Recall | F1 |",
        "|---|---:|---:|---:|",
    ]
    for label in LABELS:
        result = aggregate["per_class"][label]
        lines.append(
            f"| {label} | {result['precision']:.4f} | {result['recall']:.4f} | {result['f1']:.4f} |"
        )
    (output_dir / "CASCADE_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"aggregate": aggregate, "gate": gate}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
