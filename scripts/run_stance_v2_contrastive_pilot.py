"""Run the bounded Stance V2 contrastive pilot.

The pilot fine-tunes a Spanish XNLI encoder as a direct four-class pair
classifier. It combines the frozen 198-record development corpus with 16 of the
20 Challenge-04 contexts and predicts the remaining four contexts. Five-fold
grouped cross-validation yields one out-of-fold prediction for every Challenge
04 pair without training on its context.

Challenge 04 is development data for V2. This script does not create a final
model and must never be used to report Challenge 04 as V2's external test.
"""

from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import json
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from torch.optim import AdamW
from torch.utils.data import DataLoader, Dataset
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    DataCollatorWithPadding,
    get_linear_schedule_with_warmup,
)


LABELS = ["unrelated", "discuss", "agree", "disagree"]
LABEL_TO_ID = {label: index for index, label in enumerate(LABELS)}
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
DEFAULT_OUTPUT = PROJECT / "output" / "stance_es_pe_v2" / "phase0_contrastive_pilot"


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def clean(text: str) -> str:
    return " ".join((text or "").split())


def load_v1_rows() -> list[dict]:
    stances = read_csv(V1_TRAINING / "development_all_stances.csv")
    bodies = {
        row["Body ID"]: row["articleBody"]
        for row in read_csv(V1_TRAINING / "development_all_bodies.csv")
    }
    metadata = {
        row["Body ID"]: row
        for row in read_csv(V1_TRAINING / "development_all_metadata.csv")
    }
    rows = []
    for row in stances:
        body_id = row["Body ID"]
        label = row["Stance"].casefold()
        rows.append({
            "pair_id": metadata[body_id]["pair_id"],
            "group_id": metadata[body_id]["group_id"],
            "claim": clean(row["Headline"]),
            "context": clean(bodies[body_id]),
            "label": label,
            "origin": "v1_development",
        })
    return rows


def load_challenge_rows() -> list[dict]:
    raw = json.loads(CHALLENGE_GOLD.read_text(encoding="utf-8"))
    rows = []
    for row in raw:
        rows.append({
            "pair_id": row["pair_id"],
            "group_id": row["group_id"],
            "claim": clean(row["claim"]),
            "context": clean(f"{row.get('title', '')} {row.get('context', '')}"),
            "label": str(row["gold_label"]).casefold(),
            "origin": "challenge_04_contrastive_development",
        })
    return rows


def build_folds(groups: list[str], seed: int, n_splits: int = 5) -> list[list[str]]:
    shuffled = sorted(groups)
    random.Random(seed).shuffle(shuffled)
    folds = [[] for _ in range(n_splits)]
    for index, group in enumerate(shuffled):
        folds[index % n_splits].append(group)
    return [sorted(fold) for fold in folds]


class PairDataset(Dataset):
    def __init__(self, rows: list[dict], tokenizer, max_length: int):
        self.rows = rows
        self.encodings = tokenizer(
            [row["claim"] for row in rows],
            [row["context"] for row in rows],
            truncation="only_second",
            max_length=max_length,
            padding=False,
        )

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict:
        item = {key: value[index] for key, value in self.encodings.items()}
        item["labels"] = LABEL_TO_ID[self.rows[index]["label"]]
        return item


def make_loader(
    rows: list[dict],
    tokenizer,
    max_length: int,
    batch_size: int,
    shuffle: bool,
    seed: int,
) -> DataLoader:
    dataset = PairDataset(rows, tokenizer, max_length)
    generator = torch.Generator()
    generator.manual_seed(seed)
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        generator=generator if shuffle else None,
        collate_fn=DataCollatorWithPadding(tokenizer=tokenizer, return_tensors="pt"),
    )


def evaluate(model, loader: DataLoader, rows: list[dict], device: torch.device) -> tuple[dict, list[dict]]:
    model.eval()
    predictions: list[dict] = []
    cursor = 0
    with torch.no_grad():
        for batch in loader:
            labels = batch.pop("labels")
            inputs = {key: value.to(device) for key, value in batch.items()}
            logits = model(**inputs).logits
            probabilities = torch.softmax(logits, dim=-1).cpu().numpy()
            for gold_id, probs in zip(labels.tolist(), probabilities):
                row = rows[cursor]
                predicted_id = int(np.argmax(probs))
                predictions.append({
                    "pair_id": row["pair_id"],
                    "group_id": row["group_id"],
                    "gold_label": LABELS[gold_id],
                    "prediction": LABELS[predicted_id],
                    "confidence": float(probs[predicted_id]),
                    **{f"p_{label}": float(probs[index]) for index, label in enumerate(LABELS)},
                })
                cursor += 1
    return compute_metrics(predictions), predictions


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


def train_fold(
    *,
    fold_index: int,
    train_rows: list[dict],
    validation_rows: list[dict],
    tokenizer,
    args,
    device: torch.device,
) -> tuple[dict, list[dict]]:
    fold_seed = args.seed + fold_index
    set_seed(fold_seed)
    train_loader = make_loader(
        train_rows, tokenizer, args.max_length, args.batch_size, True, fold_seed
    )
    validation_loader = make_loader(
        validation_rows, tokenizer, args.max_length, args.eval_batch_size, False, fold_seed
    )
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model,
        num_labels=len(LABELS),
        ignore_mismatched_sizes=True,
        id2label={index: label for index, label in enumerate(LABELS)},
        label2id=LABEL_TO_ID,
    ).to(device)
    optimizer = AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    updates_per_epoch = int(np.ceil(len(train_loader) / args.gradient_accumulation_steps))
    total_updates = updates_per_epoch * args.epochs
    scheduler = get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=int(total_updates * args.warmup_ratio),
        num_training_steps=total_updates,
    )
    criterion = nn.CrossEntropyLoss()
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")
    history = []

    for epoch in range(1, args.epochs + 1):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        running_loss = 0.0
        optimizer_steps = 0
        for batch_index, batch in enumerate(train_loader, start=1):
            labels = batch.pop("labels").to(device)
            inputs = {key: value.to(device) for key, value in batch.items()}
            with torch.amp.autocast("cuda", enabled=device.type == "cuda"):
                logits = model(**inputs).logits
                loss = criterion(logits, labels) / args.gradient_accumulation_steps
            scaler.scale(loss).backward()
            running_loss += float(loss.item()) * args.gradient_accumulation_steps
            should_step = (
                batch_index % args.gradient_accumulation_steps == 0
                or batch_index == len(train_loader)
            )
            if should_step:
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), args.max_grad_norm)
                scaler.step(optimizer)
                scaler.update()
                scheduler.step()
                optimizer.zero_grad(set_to_none=True)
                optimizer_steps += 1
        validation_metrics, _ = evaluate(model, validation_loader, validation_rows, device)
        summary = {
            "epoch": epoch,
            "train_loss": running_loss / max(1, len(train_loader)),
            "optimizer_steps": optimizer_steps,
            "validation_macro_f1": validation_metrics["macro_f1_fixed_four"],
            "validation_accuracy": validation_metrics["accuracy"],
        }
        history.append(summary)
        print(f"fold={fold_index} {json.dumps(summary, ensure_ascii=False)}", flush=True)

    final_metrics, predictions = evaluate(model, validation_loader, validation_rows, device)
    payload = {
        "fold": fold_index,
        "seed": fold_seed,
        "train_records": len(train_rows),
        "validation_records": len(validation_rows),
        "validation_groups": sorted({row["group_id"] for row in validation_rows}),
        "history": history,
        "final_metrics": final_metrics,
    }
    del model, optimizer, scheduler, scaler, train_loader, validation_loader
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return payload, predictions


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read_predictions(path: Path) -> list[dict]:
    rows = read_csv(path)
    numeric = ["confidence", *[f"p_{label}" for label in LABELS]]
    for row in rows:
        for field in numeric:
            row[field] = float(row[field])
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--output_dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch_size", type=int, default=2)
    parser.add_argument("--eval_batch_size", type=int, default=8)
    parser.add_argument("--gradient_accumulation_steps", type=int, default=2)
    parser.add_argument("--learning_rate", type=float, default=1e-5)
    parser.add_argument("--weight_decay", type=float, default=0.01)
    parser.add_argument("--warmup_ratio", type=float, default=0.1)
    parser.add_argument("--max_grad_norm", type=float, default=1.0)
    parser.add_argument("--max_length", type=int, default=256)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--smoke_only", action="store_true")
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    v1_rows = load_v1_rows()
    challenge_rows = load_challenge_rows()
    challenge_groups = sorted({row["group_id"] for row in challenge_rows})
    if len(challenge_rows) != 80 or len(challenge_groups) != 20:
        raise SystemExit("Challenge 04 no tiene la estructura esperada de 80 pares y 20 contextos.")
    for group in challenge_groups:
        labels = sorted(row["label"] for row in challenge_rows if row["group_id"] == group)
        if labels != sorted(LABELS):
            raise SystemExit(f"El grupo {group} no contiene exactamente las cuatro clases.")

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if args.smoke_only:
        model = AutoModelForSequenceClassification.from_pretrained(
            args.model,
            num_labels=len(LABELS),
            ignore_mismatched_sizes=True,
        ).to(device)
        loader = make_loader(challenge_rows[:4], tokenizer, args.max_length, 2, False, args.seed)
        batch = next(iter(loader))
        labels = batch.pop("labels").to(device)
        inputs = {key: value.to(device) for key, value in batch.items()}
        loss = nn.CrossEntropyLoss()(model(**inputs).logits, labels)
        loss.backward()
        print(json.dumps({"status": "SMOKE_OK", "device": str(device), "loss": float(loss.item())}))
        return

    folds = build_folds(challenge_groups, args.seed)
    all_predictions: list[dict] = []
    fold_payloads: list[dict] = []
    for fold_index, validation_groups in enumerate(folds, start=1):
        fold_dir = output_dir / f"fold_{fold_index}"
        metrics_path = fold_dir / "fold_metrics.json"
        predictions_path = fold_dir / "fold_predictions.csv"
        if metrics_path.exists() and predictions_path.exists():
            print(f"fold={fold_index} ya existe; se reutiliza.", flush=True)
            fold_payloads.append(json.loads(metrics_path.read_text(encoding="utf-8")))
            all_predictions.extend(read_predictions(predictions_path))
            continue

        validation_group_set = set(validation_groups)
        contrastive_train = [
            row for row in challenge_rows if row["group_id"] not in validation_group_set
        ]
        validation_rows = [
            row for row in challenge_rows if row["group_id"] in validation_group_set
        ]
        train_rows = [*v1_rows, *contrastive_train]
        fold_payload, predictions = train_fold(
            fold_index=fold_index,
            train_rows=train_rows,
            validation_rows=validation_rows,
            tokenizer=tokenizer,
            args=args,
            device=device,
        )
        fold_dir.mkdir(parents=True, exist_ok=True)
        metrics_path.write_text(
            json.dumps(fold_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        write_csv(predictions_path, predictions)
        fold_payloads.append(fold_payload)
        all_predictions.extend(predictions)

    if len(all_predictions) != 80 or len({row["pair_id"] for row in all_predictions}) != 80:
        raise SystemExit("Las predicciones out-of-fold no cubren exactamente los 80 pares.")
    all_predictions.sort(key=lambda row: row["pair_id"])
    aggregate_metrics = compute_metrics(all_predictions)
    gate = {
        "macro_f1_at_least_0_60": aggregate_metrics["macro_f1_fixed_four"] >= 0.60,
        "disagree_f1_at_least_0_50": aggregate_metrics["per_class"]["disagree"]["f1"] >= 0.50,
        "disagree_recall_at_least_0_50": aggregate_metrics["per_class"]["disagree"]["recall"] >= 0.50,
        "minimum_class_f1_at_least_0_40": min(
            result["f1"] for result in aggregate_metrics["per_class"].values()
        ) >= 0.40,
        "all_four_classes_predicted": set(aggregate_metrics["prediction_counts"]) == set(LABELS),
    }
    gate["development_go"] = all(gate.values())
    payload = {
        "status": "COMPLETE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "epistemic_role": "V2 development-only grouped contrastive pilot",
        "model": args.model,
        "device": str(device),
        "configuration": {
            key: value
            for key, value in vars(args).items()
            if key not in {"output_dir", "smoke_only"}
        },
        "data": {
            "v1_records_in_every_training_fold": len(v1_rows),
            "challenge_records": len(challenge_rows),
            "challenge_groups": len(challenge_groups),
            "training_challenge_groups_per_fold": 16,
            "validation_challenge_groups_per_fold": 4,
            "challenge_gold_sha256": sha256_file(CHALLENGE_GOLD),
        },
        "folds": fold_payloads,
        "aggregate_out_of_fold_metrics": aggregate_metrics,
        "development_gate": gate,
    }
    write_csv(output_dir / "oof_predictions.csv", all_predictions)
    (output_dir / "pilot_metrics.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    per_class = aggregate_metrics["per_class"]
    lines = [
        "# Stance V2 — piloto contrastivo agrupado",
        "",
        f"- Modelo inicial: `{args.model}`.",
        "- Evaluación: cinco folds por contexto; cada par de Challenge 04 se predice sin entrenar con su contexto.",
        f"- Macro-F1 out-of-fold: **{aggregate_metrics['macro_f1_fixed_four']:.4f}**.",
        f"- Accuracy: **{aggregate_metrics['accuracy']:.4f}**.",
        f"- Decisión de desarrollo: **{'GO' if gate['development_go'] else 'NO GO'}**.",
        "",
        "| Clase | Precisión | Recall | F1 |",
        "|---|---:|---:|---:|",
    ]
    for label in LABELS:
        result = per_class[label]
        lines.append(
            f"| {label} | {result['precision']:.4f} | {result['recall']:.4f} | {result['f1']:.4f} |"
        )
    (output_dir / "PILOT_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"aggregate": aggregate_metrics, "gate": gate}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
