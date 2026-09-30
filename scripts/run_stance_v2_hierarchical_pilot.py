"""Run the final bounded hierarchical Stance V2 pilot.

Stage A reuses the out-of-fold related/unrelated decisions from the lightweight
cascade. Stage B fine-tunes the original three-way Spanish-XNLI checkpoint on
local related examples only, preserving its contradiction/neutral/entailment
head. Five grouped folds produce one out-of-fold four-class prediction for each
Challenge-04 pair.
"""

from __future__ import annotations

import argparse
import csv
import gc
import json
import random
from collections import Counter
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


STANCE_LABELS = ["unrelated", "discuss", "agree", "disagree"]
STANCE_TO_NLI = {"disagree": 0, "discuss": 1, "agree": 2}
NLI_TO_STANCE = {0: "disagree", 1: "discuss", 2: "agree"}
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
STAGE_A_PREDICTIONS = (
    PROJECT / "output" / "stance_es_pe_v2" / "phase0_lightweight_cascade" / "cascade_oof_predictions.csv"
)
DEFAULT_OUTPUT = PROJECT / "output" / "stance_es_pe_v2" / "phase0_hierarchical_pilot"


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def clean(text: str) -> str:
    return " ".join((text or "").split())


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_rows() -> tuple[list[dict], list[dict], dict[str, dict]]:
    stances = read_csv(V1_TRAINING / "development_all_stances.csv")
    bodies = {
        row["Body ID"]: row["articleBody"]
        for row in read_csv(V1_TRAINING / "development_all_bodies.csv")
    }
    metadata = {
        row["Body ID"]: row
        for row in read_csv(V1_TRAINING / "development_all_metadata.csv")
    }
    v1_related = []
    for row in stances:
        label = row["Stance"].casefold()
        if label == "unrelated":
            continue
        body_id = row["Body ID"]
        v1_related.append({
            "pair_id": metadata[body_id]["pair_id"],
            "group_id": metadata[body_id]["group_id"],
            "claim": clean(row["Headline"]),
            "context": clean(bodies[body_id]),
            "label": label,
            "origin": "v1_related_development",
        })

    challenge_raw = json.loads(CHALLENGE_GOLD.read_text(encoding="utf-8"))
    challenge = [
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
    stage_a = {row["pair_id"]: row for row in read_csv(STAGE_A_PREDICTIONS)}
    if set(stage_a) != {row["pair_id"] for row in challenge}:
        raise SystemExit("Las predicciones de Stage A no coinciden con Challenge 04.")
    return v1_related, challenge, stage_a


class PairDataset(Dataset):
    def __init__(self, rows: list[dict], tokenizer, max_length: int, include_unrelated: bool = False):
        self.rows = rows
        self.encodings = tokenizer(
            [row["context"] for row in rows],
            [row["claim"] for row in rows],
            truncation="only_first",
            max_length=max_length,
            padding=False,
        )
        self.include_unrelated = include_unrelated

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict:
        item = {key: value[index] for key, value in self.encodings.items()}
        if not self.include_unrelated:
            item["labels"] = STANCE_TO_NLI[self.rows[index]["label"]]
        return item


def loader(rows, tokenizer, args, *, training: bool, seed: int, include_unrelated: bool = False):
    dataset = PairDataset(rows, tokenizer, args.max_length, include_unrelated=include_unrelated)
    generator = torch.Generator()
    generator.manual_seed(seed)
    return DataLoader(
        dataset,
        batch_size=args.batch_size if training else args.eval_batch_size,
        shuffle=training,
        generator=generator if training else None,
        collate_fn=DataCollatorWithPadding(tokenizer=tokenizer, return_tensors="pt"),
    )


def predict_nli(model, data_loader: DataLoader, rows: list[dict], device: torch.device) -> list[dict]:
    model.eval()
    output = []
    cursor = 0
    with torch.no_grad():
        for batch in data_loader:
            batch.pop("labels", None)
            inputs = {key: value.to(device) for key, value in batch.items()}
            probabilities = torch.softmax(model(**inputs).logits, dim=-1).cpu().numpy()
            for probs in probabilities:
                row = rows[cursor]
                prediction_id = int(np.argmax(probs))
                output.append({
                    "pair_id": row["pair_id"],
                    "nli_prediction": NLI_TO_STANCE[prediction_id],
                    "nli_confidence": float(probs[prediction_id]),
                    "p_disagree": float(probs[0]),
                    "p_discuss": float(probs[1]),
                    "p_agree": float(probs[2]),
                })
                cursor += 1
    return output


def compute_metrics(rows: list[dict]) -> dict:
    y_true = [row["gold_label"] for row in rows]
    y_pred = [row["prediction"] for row in rows]
    report = classification_report(
        y_true, y_pred, labels=STANCE_LABELS, output_dict=True, zero_division=0
    )
    return {
        "n": len(rows),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1_fixed_four": float(
            f1_score(y_true, y_pred, labels=STANCE_LABELS, average="macro", zero_division=0)
        ),
        "prediction_counts": dict(Counter(y_pred)),
        "per_class": {
            label: {
                "precision": float(report[label]["precision"]),
                "recall": float(report[label]["recall"]),
                "f1": float(report[label]["f1-score"]),
                "support": int(report[label]["support"]),
            }
            for label in STANCE_LABELS
        },
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=STANCE_LABELS).tolist(),
    }


def train_fold(fold_index, train_rows, validation_rows, tokenizer, args, device):
    seed = args.seed + fold_index
    set_seed(seed)
    train_loader = loader(train_rows, tokenizer, args, training=True, seed=seed)
    validation_loader = loader(
        validation_rows, tokenizer, args, training=False, seed=seed, include_unrelated=True
    )
    model = AutoModelForSequenceClassification.from_pretrained(args.model).to(device)
    if model.config.num_labels != 3:
        raise SystemExit(f"Se esperaba una cabeza NLI de tres clases; num_labels={model.config.num_labels}")
    optimizer = AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    updates_per_epoch = int(np.ceil(len(train_loader) / args.gradient_accumulation_steps))
    total_updates = updates_per_epoch * args.epochs
    scheduler = get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=int(total_updates * args.warmup_ratio),
        num_training_steps=total_updates,
    )
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")
    criterion = nn.CrossEntropyLoss()
    history = []
    for epoch in range(1, args.epochs + 1):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        total_loss = 0.0
        for batch_index, batch in enumerate(train_loader, start=1):
            labels = batch.pop("labels").to(device)
            inputs = {key: value.to(device) for key, value in batch.items()}
            with torch.amp.autocast("cuda", enabled=device.type == "cuda"):
                loss = criterion(model(**inputs).logits, labels) / args.gradient_accumulation_steps
            scaler.scale(loss).backward()
            total_loss += float(loss.item()) * args.gradient_accumulation_steps
            if batch_index % args.gradient_accumulation_steps == 0 or batch_index == len(train_loader):
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), args.max_grad_norm)
                scaler.step(optimizer)
                scaler.update()
                scheduler.step()
                optimizer.zero_grad(set_to_none=True)
        history.append({"epoch": epoch, "train_loss": total_loss / max(1, len(train_loader))})
        print(f"fold={fold_index} epoch={epoch} loss={history[-1]['train_loss']:.6f}", flush=True)
    nli_predictions = predict_nli(model, validation_loader, validation_rows, device)
    del model, optimizer, scheduler, scaler, train_loader, validation_loader
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return history, nli_predictions


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--output_dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch_size", type=int, default=2)
    parser.add_argument("--eval_batch_size", type=int, default=8)
    parser.add_argument("--gradient_accumulation_steps", type=int, default=2)
    parser.add_argument("--learning_rate", type=float, default=5e-6)
    parser.add_argument("--weight_decay", type=float, default=0.01)
    parser.add_argument("--warmup_ratio", type=float, default=0.1)
    parser.add_argument("--max_grad_norm", type=float, default=1.0)
    parser.add_argument("--max_length", type=int, default=384)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--smoke_only", action="store_true")
    args = parser.parse_args()

    v1_related, challenge, stage_a = load_rows()
    groups = sorted({row["group_id"] for row in challenge})
    shuffled = sorted(groups)
    random.Random(args.seed).shuffle(shuffled)
    folds = [[] for _ in range(5)]
    for index, group in enumerate(shuffled):
        folds[index % 5].append(group)
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    if args.smoke_only:
        related = [row for row in challenge if row["label"] != "unrelated"][:2]
        data_loader = loader(related, tokenizer, args, training=True, seed=args.seed)
        model = AutoModelForSequenceClassification.from_pretrained(args.model).to(device)
        batch = next(iter(data_loader))
        labels = batch.pop("labels").to(device)
        inputs = {key: value.to(device) for key, value in batch.items()}
        loss = nn.CrossEntropyLoss()(model(**inputs).logits, labels)
        loss.backward()
        print(json.dumps({"status": "SMOKE_OK", "device": str(device), "loss": float(loss.item())}))
        return

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    all_predictions = []
    fold_payloads = []
    for fold_index, validation_groups in enumerate(folds, start=1):
        fold_dir = output_dir / f"fold_{fold_index}"
        fold_json = fold_dir / "fold_metrics.json"
        fold_csv = fold_dir / "fold_predictions.csv"
        if fold_json.exists() and fold_csv.exists():
            fold_payloads.append(json.loads(fold_json.read_text(encoding="utf-8")))
            all_predictions.extend(read_csv(fold_csv))
            print(f"fold={fold_index} ya existe; se reutiliza.", flush=True)
            continue

        validation_set = set(validation_groups)
        local_train = [
            row for row in challenge
            if row["group_id"] not in validation_set and row["label"] != "unrelated"
        ]
        train_rows = [*v1_related, *local_train]
        validation_rows = [row for row in challenge if row["group_id"] in validation_set]
        history, nli_rows = train_fold(
            fold_index, train_rows, validation_rows, tokenizer, args, device
        )
        nli_by_id = {row["pair_id"]: row for row in nli_rows}
        predictions = []
        for row in validation_rows:
            relevance = float(stage_a[row["pair_id"]]["related_probability"])
            nli = nli_by_id[row["pair_id"]]
            prediction = "unrelated" if relevance < 0.5 else nli["nli_prediction"]
            predictions.append({
                "fold": fold_index,
                "pair_id": row["pair_id"],
                "group_id": row["group_id"],
                "gold_label": row["label"],
                "prediction": prediction,
                "related_probability": relevance,
                **{key: value for key, value in nli.items() if key != "pair_id"},
            })
        metrics = compute_metrics(predictions)
        payload = {
            "fold": fold_index,
            "seed": args.seed + fold_index,
            "validation_groups": sorted(validation_groups),
            "train_related_records": len(train_rows),
            "history": history,
            "metrics": metrics,
        }
        fold_dir.mkdir(parents=True, exist_ok=True)
        fold_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        write_csv(fold_csv, predictions)
        fold_payloads.append(payload)
        all_predictions.extend(predictions)

    if len(all_predictions) != 80:
        raise SystemExit(f"Se esperaban 80 predicciones y se obtuvieron {len(all_predictions)}.")
    for row in all_predictions:
        for field in ("related_probability", "nli_confidence", "p_disagree", "p_discuss", "p_agree"):
            row[field] = float(row[field])
    all_predictions.sort(key=lambda row: row["pair_id"])
    aggregate = compute_metrics(all_predictions)
    gate = {
        "macro_f1_at_least_0_60": aggregate["macro_f1_fixed_four"] >= 0.60,
        "disagree_f1_at_least_0_50": aggregate["per_class"]["disagree"]["f1"] >= 0.50,
        "disagree_recall_at_least_0_50": aggregate["per_class"]["disagree"]["recall"] >= 0.50,
        "minimum_class_f1_at_least_0_40": min(
            value["f1"] for value in aggregate["per_class"].values()
        ) >= 0.40,
        "all_four_classes_predicted": set(aggregate["prediction_counts"]) == set(STANCE_LABELS),
    }
    gate["development_go"] = all(gate.values())
    payload = {
        "status": "COMPLETE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "epistemic_role": "final bounded V2 hierarchical development pilot",
        "configuration": {key: value for key, value in vars(args).items() if key not in {"output_dir", "smoke_only"}},
        "stage_a": str(STAGE_A_PREDICTIONS),
        "folds": fold_payloads,
        "aggregate_out_of_fold_metrics": aggregate,
        "development_gate": gate,
    }
    write_csv(output_dir / "hierarchical_oof_predictions.csv", all_predictions)
    (output_dir / "hierarchical_metrics.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    lines = [
        "# Stance V2 — piloto jerárquico final",
        "",
        f"- Macro-F1 out-of-fold: **{aggregate['macro_f1_fixed_four']:.4f}**.",
        f"- Accuracy: **{aggregate['accuracy']:.4f}**.",
        f"- Decisión de desarrollo: **{'GO' if gate['development_go'] else 'NO GO'}**.",
        "",
        "| Clase | Precisión | Recall | F1 |",
        "|---|---:|---:|---:|",
    ]
    for label in STANCE_LABELS:
        result = aggregate["per_class"][label]
        lines.append(
            f"| {label} | {result['precision']:.4f} | {result['recall']:.4f} | {result['f1']:.4f} |"
        )
    (output_dir / "HIERARCHICAL_PILOT_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"aggregate": aggregate, "gate": gate}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
