"""Train and freeze the bounded hierarchical Spanish-Peruvian stance V2.

The script performs grouped five-fold development evaluation and then trains a
single final candidate on all development records. Challenge sets are never
read by this entry point.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import random
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import torch
import torch.nn as nn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.metrics.pairwise import paired_cosine_distances
from sklearn.model_selection import StratifiedGroupKFold
from torch.optim import AdamW
from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup

from evaluate_stance_v2_lightweight_cascade import infer_nli, scalar_features
from run_stance_v2_hierarchical_pilot import loader, predict_nli, set_seed, train_fold


PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = PROJECT / "data" / "processed" / "stance_es_pe_v2" / "development_v2.json"
DEFAULT_OUTPUT = PROJECT / "output" / "stance_es_pe_v2" / "final_model_2026_09_29"
DEFAULT_MODEL = "Recognai/bert-base-spanish-wwm-cased-xnli"
LABELS = ["unrelated", "discuss", "agree", "disagree"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clean(text: str) -> str:
    return " ".join((text or "").split())


def load_rows(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = [{
        **row,
        "claim": clean(row["claim"]),
        "context": clean(row["context"]),
        "label": str(row["label"]).casefold(),
    } for row in raw]
    if set(row["label"] for row in rows) != set(LABELS):
        raise ValueError("El corpus debe contener exactamente las cuatro clases.")
    if len({row["pair_id"] for row in rows}) != len(rows):
        raise ValueError("Hay pair_id duplicados.")
    return rows


def build_grouped_folds(rows: list[dict], seed: int) -> list[list[str]]:
    splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=seed)
    labels = np.asarray([row["label"] for row in rows])
    groups = np.asarray([row["group_id"] for row in rows])
    dummy = np.zeros(len(rows))
    folds = []
    for _, validation_indices in splitter.split(dummy, labels, groups):
        folds.append(sorted(set(groups[validation_indices].tolist())))
    if set().union(*(set(fold) for fold in folds)) != set(groups.tolist()):
        raise ValueError("Los folds no cubren todos los grupos.")
    return folds


def compute_metrics(rows: list[dict]) -> dict:
    y_true = [row["gold_label"] for row in rows]
    y_pred = [row["prediction"] for row in rows]
    report = classification_report(y_true, y_pred, labels=LABELS, output_dict=True, zero_division=0)
    return {
        "n": len(rows),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1_fixed_four": float(f1_score(y_true, y_pred, labels=LABELS, average="macro", zero_division=0)),
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


def fit_stage_a(train_rows: list[dict], eval_rows: list[dict], seed: int):
    word = TfidfVectorizer(strip_accents="unicode", ngram_range=(1, 2), min_df=1, sublinear_tf=True)
    char = TfidfVectorizer(strip_accents="unicode", analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True)
    texts = [text for row in train_rows for text in (row["claim"], row["context"])]
    word.fit(texts)
    char.fit(texts)

    def features(rows: list[dict]) -> np.ndarray:
        claims_word = word.transform([row["claim"] for row in rows])
        contexts_word = word.transform([row["context"] for row in rows])
        claims_char = char.transform([row["claim"] for row in rows])
        contexts_char = char.transform([row["context"] for row in rows])
        word_cosine = (1.0 - paired_cosine_distances(claims_word, contexts_word)).reshape(-1, 1)
        char_cosine = (1.0 - paired_cosine_distances(claims_char, contexts_char)).reshape(-1, 1)
        return np.hstack([scalar_features(rows), word_cosine, char_cosine])

    train_x = features(train_rows)
    eval_x = features(eval_rows)
    train_y = np.asarray([int(row["label"] != "unrelated") for row in train_rows])
    classifier = LogisticRegression(class_weight="balanced", max_iter=3000, random_state=seed)
    classifier.fit(train_x, train_y)
    return word, char, classifier, classifier.predict_proba(eval_x)[:, 1]


def write_csv(path: Path, rows: list[dict]) -> None:
    import csv
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def train_final_stage_b(rows: list[dict], tokenizer, args, device, output_dir: Path) -> list[dict]:
    related = [row for row in rows if row["label"] != "unrelated"]
    set_seed(args.seed)
    data_loader = loader(related, tokenizer, args, training=True, seed=args.seed)
    model = AutoModelForSequenceClassification.from_pretrained(args.model).to(device)
    optimizer = AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    updates_per_epoch = int(np.ceil(len(data_loader) / args.gradient_accumulation_steps))
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
        for batch_index, batch in enumerate(data_loader, start=1):
            labels = batch.pop("labels").to(device)
            inputs = {key: value.to(device) for key, value in batch.items()}
            with torch.amp.autocast("cuda", enabled=device.type == "cuda"):
                loss = criterion(model(**inputs).logits, labels) / args.gradient_accumulation_steps
            scaler.scale(loss).backward()
            total_loss += float(loss.item()) * args.gradient_accumulation_steps
            if batch_index % args.gradient_accumulation_steps == 0 or batch_index == len(data_loader):
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), args.max_grad_norm)
                scaler.step(optimizer)
                scaler.update()
                scheduler.step()
                optimizer.zero_grad(set_to_none=True)
        epoch_loss = total_loss / max(1, len(data_loader))
        history.append({"epoch": epoch, "train_loss": epoch_loss})
        print(f"final epoch={epoch} loss={epoch_loss:.6f}", flush=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)
    del model, optimizer, scheduler, scaler, data_loader
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return history


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--output_dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch_size", type=int, default=2)
    parser.add_argument("--eval_batch_size", type=int, default=8)
    parser.add_argument("--gradient_accumulation_steps", type=int, default=2)
    parser.add_argument("--learning_rate", type=float, default=5e-6)
    parser.add_argument("--weight_decay", type=float, default=0.01)
    parser.add_argument("--warmup_ratio", type=float, default=0.1)
    parser.add_argument("--max_grad_norm", type=float, default=1.0)
    parser.add_argument("--max_length", type=int, default=384)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--smoke_only", action="store_true")
    args = parser.parse_args()

    args.data = args.data.resolve()
    args.output_dir = args.output_dir.resolve()
    rows = load_rows(args.data)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    if args.smoke_only:
        sample = [row for row in rows if row["label"] != "unrelated"][:2]
        data_loader = loader(sample, tokenizer, args, training=True, seed=args.seed)
        model = AutoModelForSequenceClassification.from_pretrained(args.model).to(device)
        batch = next(iter(data_loader))
        labels = batch.pop("labels").to(device)
        inputs = {key: value.to(device) for key, value in batch.items()}
        loss = nn.CrossEntropyLoss()(model(**inputs).logits, labels)
        loss.backward()
        print(json.dumps({"status": "SMOKE_OK", "device": str(device), "records": len(rows), "loss": float(loss.item())}))
        return

    if (args.output_dir / "model_freeze_manifest.json").exists():
        raise FileExistsError(f"El modelo final ya está congelado y no se sobrescribirá: {args.output_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    development_dir = args.output_dir / "development_grouped_cv"
    development_dir.mkdir(parents=True, exist_ok=True)

    nli_cache = development_dir / "base_nli_features.json"
    if nli_cache.exists():
        cached = {row["pair_id"]: row for row in json.loads(nli_cache.read_text(encoding="utf-8"))}
        if set(cached) != {row["pair_id"] for row in rows}:
            raise ValueError("El caché NLI no coincide con el corpus actual.")
        for row in rows:
            row.update(cached[row["pair_id"]])
    else:
        infer_nli(rows, args.model, args.eval_batch_size, args.max_length)
        cache_rows = [{
            "pair_id": row["pair_id"],
            "p_contradiction": row["p_contradiction"],
            "p_neutral": row["p_neutral"],
            "p_entailment": row["p_entailment"],
            "nli_prediction": row["nli_prediction"],
        } for row in rows]
        nli_cache.write_text(json.dumps(cache_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    folds = build_grouped_folds(rows, args.seed)
    all_predictions = []
    fold_payloads = []
    for fold_index, validation_groups in enumerate(folds, start=1):
        fold_dir = development_dir / f"fold_{fold_index}"
        fold_json = fold_dir / "fold_metrics.json"
        fold_csv = fold_dir / "fold_predictions.csv"
        if fold_json.exists() and fold_csv.exists():
            import csv
            with fold_csv.open("r", encoding="utf-8-sig", newline="") as handle:
                all_predictions.extend(list(csv.DictReader(handle)))
            fold_payloads.append(json.loads(fold_json.read_text(encoding="utf-8")))
            print(f"fold={fold_index} ya existe; se reutiliza.", flush=True)
            continue
        validation_set = set(validation_groups)
        train_rows = [row for row in rows if row["group_id"] not in validation_set]
        validation_rows = [row for row in rows if row["group_id"] in validation_set]
        _, _, stage_a, relevance = fit_stage_a(train_rows, validation_rows, args.seed + fold_index)
        related_train = [row for row in train_rows if row["label"] != "unrelated"]
        history, nli_predictions = train_fold(
            fold_index, related_train, validation_rows, tokenizer, args, device
        )
        nli_by_id = {row["pair_id"]: row for row in nli_predictions}
        predictions = []
        for row, related_probability in zip(validation_rows, relevance):
            nli = nli_by_id[row["pair_id"]]
            prediction = "unrelated" if related_probability < args.threshold else nli["nli_prediction"]
            predictions.append({
                "fold": fold_index,
                "pair_id": row["pair_id"],
                "group_id": row["group_id"],
                "origin": row["origin"],
                "gold_label": row["label"],
                "prediction": prediction,
                "related_probability": float(related_probability),
                **{key: value for key, value in nli.items() if key != "pair_id"},
            })
        metrics = compute_metrics(predictions)
        payload = {
            "fold": fold_index,
            "validation_groups": validation_groups,
            "train_records": len(train_rows),
            "train_related_records": len(related_train),
            "validation_records": len(validation_rows),
            "history": history,
            "metrics": metrics,
            "stage_a_coefficients": stage_a.coef_[0].tolist(),
            "stage_a_intercept": float(stage_a.intercept_[0]),
        }
        fold_dir.mkdir(parents=True, exist_ok=True)
        write_csv(fold_csv, predictions)
        fold_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        all_predictions.extend(predictions)
        fold_payloads.append(payload)
        print(f"fold={fold_index} macro_f1={metrics['macro_f1_fixed_four']:.4f}", flush=True)

    for row in all_predictions:
        for field in ("related_probability", "nli_confidence", "p_disagree", "p_discuss", "p_agree"):
            row[field] = float(row[field])
    all_predictions.sort(key=lambda row: row["pair_id"])
    if len(all_predictions) != len(rows):
        raise ValueError(f"Se esperaban {len(rows)} predicciones OOF y se obtuvieron {len(all_predictions)}.")
    aggregate = compute_metrics(all_predictions)
    write_csv(development_dir / "hierarchical_oof_predictions.csv", all_predictions)
    cv_payload = {
        "status": "COMPLETE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "epistemic_role": "grouped internal development evaluation; not external performance",
        "records": len(rows),
        "groups": len({row["group_id"] for row in rows}),
        "configuration": {
            "model": args.model,
            "epochs": args.epochs,
            "learning_rate": args.learning_rate,
            "max_length": args.max_length,
            "threshold": args.threshold,
            "seed": args.seed,
        },
        "folds": fold_payloads,
        "aggregate_out_of_fold_metrics": aggregate,
    }
    (development_dir / "hierarchical_cv_metrics.json").write_text(
        json.dumps(cv_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    word, char, stage_a, _ = fit_stage_a(rows, rows, args.seed)
    joblib.dump({
        "word_vectorizer": word,
        "char_vectorizer": char,
        "classifier": stage_a,
        "threshold": args.threshold,
        "feature_order": [
            "jaccard_tokens", "claim_coverage", "context_coverage", "token_length_ratio",
            "claim_number_coverage", "all_claim_numbers_present", "p_contradiction",
            "p_neutral", "p_entailment", "nli_entropy", "nli_max", "nli_margin",
            "word_tfidf_cosine", "char_tfidf_cosine",
        ],
    }, args.output_dir / "stage_a_relevance.joblib")

    stage_a_base = args.output_dir / "stage_a_base_nli"
    base_model = AutoModelForSequenceClassification.from_pretrained(args.model)
    base_model.save_pretrained(stage_a_base)
    tokenizer.save_pretrained(stage_a_base)
    del base_model
    final_history = train_final_stage_b(rows, tokenizer, args, device, args.output_dir / "stage_b_relation")

    serving = {
        "architecture": "hierarchical_stance_v2",
        "label_names": LABELS,
        "stage_a": {
            "model": "stage_a_relevance.joblib",
            "base_nli_model": "stage_a_base_nli",
            "threshold": args.threshold,
        },
        "stage_b": {
            "model": "stage_b_relation",
            "id_to_stance": {"0": "disagree", "1": "discuss", "2": "agree"},
        },
        "max_length": args.max_length,
        "input_contract": {"text_a": "context/evidence", "text_b": "claim"},
        "public_enabled": False,
        "status": "frozen_awaiting_challenge_05_and_operational_evaluation",
    }
    (args.output_dir / "serving_config.json").write_text(
        json.dumps(serving, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    manifest = {
        "status": "FROZEN_AWAITING_CHALLENGE_05_AND_OPERATIONAL_EVALUATION",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "corpus": {
            "path": str(args.data),
            "sha256": sha256_file(args.data),
            "records": len(rows),
            "groups": len({row["group_id"] for row in rows}),
            "label_counts": dict(sorted(Counter(row["label"] for row in rows).items())),
        },
        "development_evaluation": {
            "metrics_path": str(development_dir / "hierarchical_cv_metrics.json"),
            "macro_f1": aggregate["macro_f1_fixed_four"],
            "per_class": aggregate["per_class"],
            "warning": "Internal grouped development estimate; not the final external result.",
        },
        "training": {
            "model_family": args.model,
            "epochs": args.epochs,
            "learning_rate": args.learning_rate,
            "batch_size": args.batch_size,
            "gradient_accumulation_steps": args.gradient_accumulation_steps,
            "max_length": args.max_length,
            "seed": args.seed,
            "final_history": final_history,
        },
        "separation": {
            "challenge_04_read_by_training_script": False,
            "challenge_05_read_by_training_script": False,
            "operational_evaluation_read_by_training_script": False,
        },
    }
    (args.output_dir / "model_freeze_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "status": manifest["status"],
        "output_dir": str(args.output_dir),
        "device": str(device),
        "development_macro_f1": aggregate["macro_f1_fixed_four"],
        "per_class": aggregate["per_class"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
