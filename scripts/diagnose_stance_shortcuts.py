"""Diagnose lexical and source shortcuts in the local stance development corpus."""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.stats import chi2_contingency
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder


LABELS = ("unrelated", "discuss", "agree", "disagree")
SPLITS = ("train", "validation", "test")
VERDICT_CUES = (
    "es falso", "es falsa", "lo falso", "no fue realizada", "no corresponde",
    "no es cierto", "carece de validez", "son invalidas", "es imprecisa",
)


def normalized(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").casefold()
    text = "".join(char for char in unicodedata.normalize("NFD", text) if unicodedata.category(char) != "Mn")
    text = re.sub(r"[^\w%]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_split(prepared: Path, split: str) -> list[dict]:
    base = prepared / "document_prefix" / "fnc"
    stances = read_csv(base / f"{split}_stances.csv")
    bodies = {row["Body ID"]: row["articleBody"] for row in read_csv(base / f"{split}_bodies.csv")}
    metadata = {row["Body ID"]: row for row in read_csv(base / f"{split}_metadata.csv")}
    return [
        {
            "split": split,
            "pair_id": metadata[row["Body ID"]]["pair_id"],
            "group_id": metadata[row["Body ID"]]["group_id"],
            "source": metadata[row["Body ID"]]["source_name"],
            "label": row["Stance"].casefold(),
            "claim": row["Headline"],
            "body": bodies[row["Body ID"]],
            "prefix": bodies[row["Body ID"]][:300],
        }
        for row in stances
    ]


def select_field(field: str):
    return FunctionTransformer(lambda rows: [row[field] for row in rows], validate=False)


def text_model(field: str) -> Pipeline:
    features = FeatureUnion(
        [
            (
                "word",
                Pipeline(
                    [
                        ("select", select_field(field)),
                        ("tfidf", TfidfVectorizer(strip_accents="unicode", ngram_range=(1, 2), min_df=1, sublinear_tf=True)),
                    ]
                ),
            ),
            (
                "char",
                Pipeline(
                    [
                        ("select", select_field(field)),
                        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True)),
                    ]
                ),
            ),
        ]
    )
    return Pipeline(
        [
            ("features", features),
            ("classifier", LogisticRegression(max_iter=3000, class_weight="balanced", random_state=42)),
        ]
    )


def source_model() -> Pipeline:
    transformer = ColumnTransformer(
        [("source", OneHotEncoder(handle_unknown="ignore"), [0])],
        remainder="drop",
    )
    return Pipeline(
        [
            ("features", transformer),
            ("classifier", LogisticRegression(max_iter=3000, class_weight="balanced", random_state=42)),
        ]
    )


def evaluate(model, train_x, train_y, eval_x, eval_y) -> dict:
    model.fit(train_x, train_y)
    predictions = model.predict(eval_x)
    report = classification_report(eval_y, predictions, labels=LABELS, output_dict=True, zero_division=0)
    return {
        "macro_f1": float(f1_score(eval_y, predictions, labels=LABELS, average="macro", zero_division=0)),
        "accuracy": float(accuracy_score(eval_y, predictions)),
        "per_class_f1": {label: float(report[label]["f1-score"]) for label in LABELS},
        "predicted_counts": dict(Counter(predictions)),
    }


def source_association(rows: list[dict]) -> dict:
    sources = sorted({row["source"] for row in rows})
    table = np.array(
        [[sum(row["source"] == source and row["label"] == label for row in rows) for label in LABELS] for source in sources],
        dtype=float,
    )
    chi2, p_value, _, _ = chi2_contingency(table)
    n = table.sum()
    denominator = min(table.shape[0] - 1, table.shape[1] - 1)
    cramers_v = float(np.sqrt((chi2 / n) / denominator)) if denominator > 0 else 0.0
    return {
        "sources": sources,
        "labels": LABELS,
        "contingency_table": table.astype(int).tolist(),
        "chi_square": float(chi2),
        "p_value": float(p_value),
        "cramers_v": cramers_v,
    }


def cue_audit(rows: list[dict]) -> dict:
    output = {}
    for label in LABELS:
        selected = [row for row in rows if row["label"] == label]
        cue_hits = sum(any(cue in normalized(row["prefix"]) for cue in VERDICT_CUES) for row in selected)
        starts = sum(normalized(row["body"]).startswith(normalized(row["claim"])) for row in selected)
        output[label] = {
            "records": len(selected),
            "verdict_cue_in_first_300_chars": cue_hits,
            "verdict_cue_rate": cue_hits / len(selected),
            "body_starts_with_claim": starts,
            "body_starts_with_claim_rate": starts / len(selected),
        }
    return output


def duplicate_audit(rows_by_split: dict[str, list[dict]]) -> dict:
    train = rows_by_split["train"]
    comparisons = {}
    train_norm = defaultdict(list)
    for row in train:
        train_norm[normalized(row["claim"])].append(row)
    for split in ("validation", "test"):
        exact = []
        for row in rows_by_split[split]:
            matches = train_norm.get(normalized(row["claim"]), [])
            for match in matches:
                exact.append(
                    {
                        "evaluation_pair_id": row["pair_id"],
                        "train_pair_id": match["pair_id"],
                        "evaluation_label": row["label"],
                        "train_label": match["label"],
                        "claim": row["claim"],
                    }
                )
        all_rows = train + rows_by_split[split]
        vectorizer = TfidfVectorizer(strip_accents="unicode", analyzer="char_wb", ngram_range=(3, 5), min_df=1)
        matrix = vectorizer.fit_transform([row["claim"] for row in all_rows])
        similarities = (matrix[len(train):] @ matrix[:len(train)].T).toarray()
        near = []
        for index, row in enumerate(rows_by_split[split]):
            best_index = int(np.argmax(similarities[index]))
            score = float(similarities[index, best_index])
            if score >= 0.80:
                match = train[best_index]
                near.append(
                    {
                        "similarity": score,
                        "evaluation_pair_id": row["pair_id"],
                        "train_pair_id": match["pair_id"],
                        "evaluation_label": row["label"],
                        "train_label": match["label"],
                        "evaluation_claim": row["claim"],
                        "train_claim": match["claim"],
                    }
                )
        comparisons[split] = {
            "exact_claim_matches": exact,
            "near_claim_matches_at_0_80": sorted(near, key=lambda item: item["similarity"], reverse=True),
        }
    return comparisons


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepared_dir", type=Path, required=True)
    parser.add_argument("--output_dir", type=Path, required=True)
    args = parser.parse_args()
    prepared = args.prepared_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    rows_by_split = {split: load_split(prepared, split) for split in SPLITS}
    train = rows_by_split["train"]
    train_y = [row["label"] for row in train]

    baselines: dict[str, dict[str, dict]] = {}
    for name, model, train_x in (
        ("source_only", source_model(), [[row["source"]] for row in train]),
        ("claim_only", text_model("claim"), train),
        ("first_300_chars_only", text_model("prefix"), train),
        ("document_only", text_model("body"), train),
    ):
        baselines[name] = {}
        for split in ("validation", "test"):
            evaluation = rows_by_split[split]
            eval_x = [[row["source"]] for row in evaluation] if name == "source_only" else evaluation
            baselines[name][split] = evaluate(
                model, train_x, train_y, eval_x, [row["label"] for row in evaluation]
            )

    all_rows = [row for split in SPLITS for row in rows_by_split[split]]
    payload = {
        "status": "COMPLETE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Detect source, lexical, title, and duplicate shortcuts before final stance claims",
        "source_label_association": source_association(all_rows),
        "cue_audit": cue_audit(all_rows),
        "duplicate_audit": duplicate_audit(rows_by_split),
        "lightweight_baselines": baselines,
    }
    json_path = output_dir / "shortcut_diagnostic.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    source_v = payload["source_label_association"]["cramers_v"]
    lines = [
        "# Diagnóstico de atajos del corpus de stance",
        "",
        f"- Asociación fuente–etiqueta (V de Cramér): **{source_v:.4f}**.",
        f"- Coincidencias exactas de claim train–validación: **{len(payload['duplicate_audit']['validation']['exact_claim_matches'])}**.",
        f"- Coincidencias exactas de claim train–test: **{len(payload['duplicate_audit']['test']['exact_claim_matches'])}**.",
        "",
        "## Baselines ligeros",
        "",
        "| Entrada | Validación macro-F1 | Test macro-F1 |",
        "|---|---:|---:|",
    ]
    for name, result in baselines.items():
        lines.append(f"| {name} | {result['validation']['macro_f1']:.4f} | {result['test']['macro_f1']:.4f} |")
    lines.extend(
        [
            "",
            "## Señales de superficie",
            "",
            "| Clase | Cue de veredicto en 300 caracteres | El cuerpo empieza con el claim |",
            "|---|---:|---:|",
        ]
    )
    for label, result in payload["cue_audit"].items():
        lines.append(
            f"| {label} | {result['verdict_cue_rate']:.1%} | {result['body_starts_with_claim_rate']:.1%} |"
        )
    lines.extend(
        [
            "",
            "Estas pruebas no invalidan el corpus; cuantifican cuánto rendimiento puede explicarse por el diseño de muestreo y por señales explícitas de los títulos. Deben orientar la ampliación y las ablaciones.",
        ]
    )
    markdown_path = output_dir / "SHORTCUT_DIAGNOSTIC.md"
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(markdown_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
