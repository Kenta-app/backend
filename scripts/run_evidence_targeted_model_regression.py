"""Run the current Gemini evidence policy against the frozen targeted gold set."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score


LABELS = ("supports", "refutes", "discusses", "unrelated")
POLICY_VERSION = "evidence-policy-2026-10-22-v3"
PROMPT_TEMPLATE = """Actúa como clasificador de la relación entre una afirmación y una evidencia periodística.

AFIRMACIÓN:
{claim}

FUENTE: {source_name}
TÍTULO DE LA FUENTE:
{source_title}
URL DE LA FUENTE:
{source_url}

EVIDENCIA:
{evidence_excerpt}

Clasifica únicamente la relación de esta evidencia con la afirmación completa.

Reglas:
1. Identifica los elementos materiales: actor, acción o hecho, objeto, tiempo, lugar y cantidad cuando correspondan.
2. supports: la evidencia confirma explícitamente todos los elementos materiales. En afirmaciones con dos o más hechos unidos, cada hecho es material; confirmar solo uno exige discusses. La mera coincidencia temática no basta.
3. refutes: la evidencia niega la proposición, aporta datos incompatibles con un elemento material o establece que la acusación carece de pruebas. Una negación general puede contradecir una variante específica comprendida por ella.
4. discusses: trata la misma proposición o evento concreto, pero omite, matiza o cambia un elemento material; solo informa antecedentes, reacciones o estado del proceso; o repite la afirmación sin confirmarla independientemente.
5. unrelated: solo comparte una persona, organización o tema amplio, pero no aborda el hecho o predicado central de la afirmación. No conviertas una coincidencia superficial en discusses.
6. Ante duda entre supports/refutes y discusses, usa discusses.
7. La autoridad o reputación de la fuente no determina la etiqueta; analiza el contenido.

Responde solo con JSON válido de esta forma:
{{"label":"supports|refutes|discusses|unrelated","rationale":"explicación breve en español"}}
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default=None)
    parser.add_argument("--max-retries", type=int, default=4)
    parser.add_argument(
        "--evaluation-role",
        default="fixed_pair_targeted_development_regression",
    )
    parser.add_argument("--bootstrap-repetitions", type=int, default=5000)
    parser.add_argument("--bootstrap-seed", type=int, default=20261023)
    return parser.parse_args()


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_response(text: str) -> dict[str, str]:
    cleaned = re.sub(r"```(?:json)?\s*|```", "", text or "", flags=re.IGNORECASE).strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match:
        cleaned = match.group(0)
    data = json.loads(cleaned)
    label = str(data.get("label") or "").strip().casefold()
    rationale = str(data.get("rationale") or "").strip()
    if label not in LABELS:
        raise ValueError(f"Invalid label: {label!r}")
    if not rationale:
        raise ValueError("Missing rationale")
    return {"label": label, "rationale": rationale}


def load_checkpoint(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    result: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                result[row["evidence_id"]] = row
    return result


def append_checkpoint(path: Path, row: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(len(ordered) - 1, lower + 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def grouped_bootstrap(
    rows: list[dict[str, str]],
    truth: list[str],
    predicted: list[str],
    *,
    repetitions: int,
    seed: int,
) -> dict[str, object] | None:
    if repetitions <= 0 or not rows or not all(str(row.get("group_id") or "").strip() for row in rows):
        return None
    by_group: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        by_group.setdefault(str(row["group_id"]).strip(), []).append(index)
    groups = sorted(by_group)
    rng = random.Random(seed)
    accuracy_values: list[float] = []
    macro_values: list[float] = []
    for _ in range(repetitions):
        sampled = [rng.choice(groups) for _ in groups]
        indices = [index for group in sampled for index in by_group[group]]
        sample_truth = [truth[index] for index in indices]
        sample_predicted = [predicted[index] for index in indices]
        accuracy_values.append(float(accuracy_score(sample_truth, sample_predicted)))
        macro_values.append(float(f1_score(
            sample_truth,
            sample_predicted,
            labels=LABELS,
            average="macro",
            zero_division=0,
        )))
    return {
        "resampling_unit": "group_id",
        "groups": len(groups),
        "repetitions": repetitions,
        "seed": seed,
        "accuracy_95_percentile_interval": {
            "low": percentile(accuracy_values, 0.025),
            "high": percentile(accuracy_values, 0.975),
        },
        "macro_f1_four_class_95_percentile_interval": {
            "low": percentile(macro_values, 0.025),
            "high": percentile(macro_values, 0.975),
        },
    }


def main() -> None:
    args = parse_args()
    load_dotenv(encoding="utf-8-sig")
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is not configured.")
    model = args.model or os.getenv("JUSTIFICATION_MODEL", "").strip() or "gemini-3.5-flash-lite"
    rows = read_rows(args.gold)
    if not rows:
        raise SystemExit("The gold file is empty.")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = args.output_dir / "predictions.jsonl"
    checkpoint = load_checkpoint(checkpoint_path)
    client = genai.Client(api_key=api_key)
    prompt_hash = hashlib.sha256(PROMPT_TEMPLATE.encode("utf-8")).hexdigest()

    for index, row in enumerate(rows, start=1):
        evidence_id = row["evidence_id"].strip()
        if evidence_id in checkpoint:
            print(f"[{index}/{len(rows)}] cached {evidence_id}", flush=True)
            continue
        prompt = PROMPT_TEMPLATE.format(**row)
        last_error: Exception | None = None
        for attempt in range(args.max_retries):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config={"temperature": 0, "response_mime_type": "application/json"},
                )
                parsed = parse_response(str(response.text or ""))
                prediction = {
                    "evidence_id": evidence_id,
                    "gold_stance": row["final_stance"].strip().casefold(),
                    "predicted_stance": parsed["label"],
                    "rationale": parsed["rationale"],
                    "model": model,
                    "policy_version": POLICY_VERSION,
                    "prompt_sha256": prompt_hash,
                }
                append_checkpoint(checkpoint_path, prediction)
                checkpoint[evidence_id] = prediction
                print(f"[{index}/{len(rows)}] {evidence_id}: {prediction['predicted_stance']}", flush=True)
                break
            except Exception as exc:  # external API errors are retried with bounded backoff
                last_error = exc
                if attempt + 1 >= args.max_retries:
                    raise RuntimeError(f"Failed {evidence_id} after {args.max_retries} attempts: {exc}") from exc
                delay = min(30, 2 ** attempt)
                print(f"[{index}/{len(rows)}] retry {attempt + 1}: {type(exc).__name__}", flush=True)
                time.sleep(delay)
        if last_error and evidence_id not in checkpoint:
            raise last_error

    predictions = [checkpoint[row["evidence_id"].strip()] for row in rows]
    truth = [row["gold_stance"] for row in predictions]
    predicted = [row["predicted_stance"] for row in predictions]
    observed = tuple(label for label in LABELS if label in set(truth))
    matrix = confusion_matrix(truth, predicted, labels=LABELS)
    limitations = [
        "This fixed-pair test evaluates stance reasoning; it does not evaluate web search or evidence retrieval."
    ]
    if "confirmatory" in args.evaluation_role:
        limitations.extend([
            "The controlled near-balanced sample does not estimate natural class prevalence.",
            "No pass threshold was preregistered for this evidence-policy evaluation; results are reported descriptively.",
        ])
    else:
        limitations.append(
            "The challenge was used for development and is not an independent confirmatory test."
        )
    if "supports" not in set(truth):
        limitations.append("The sample contains no gold supports cases.")
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_role": args.evaluation_role,
        "model": model,
        "policy_version": POLICY_VERSION,
        "prompt_sha256": prompt_hash,
        "sample_size": len(rows),
        "gold_label_counts": dict(Counter(truth)),
        "predicted_label_counts": dict(Counter(predicted)),
        "accuracy": float(accuracy_score(truth, predicted)),
        "macro_f1_observed_classes": float(
            f1_score(truth, predicted, labels=observed, average="macro", zero_division=0)
        ),
        "macro_f1_four_class": float(
            f1_score(truth, predicted, labels=LABELS, average="macro", zero_division=0)
        ),
        "classification_report": classification_report(
            truth, predicted, labels=LABELS, output_dict=True, zero_division=0
        ),
        "confusion_matrix_label_order": list(LABELS),
        "confusion_matrix": matrix.tolist(),
        "error_count": sum(left != right for left, right in zip(truth, predicted, strict=True)),
        "grouped_bootstrap": grouped_bootstrap(
            rows,
            truth,
            predicted,
            repetitions=args.bootstrap_repetitions,
            seed=args.bootstrap_seed,
        ),
        "limitations": limitations,
    }

    predictions_path = args.output_dir / "model_predictions.csv"
    prediction_fields = list(predictions[0].keys())
    with predictions_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=prediction_fields)
        writer.writeheader()
        writer.writerows(predictions)

    errors_path = args.output_dir / "model_errors.csv"
    error_fields = (
        "evidence_id", "claim", "source_name", "source_title", "evidence_excerpt",
        "gold_stance", "predicted_stance", "model_rationale",
    )
    by_id = {row["evidence_id"].strip(): row for row in rows}
    with errors_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=error_fields)
        writer.writeheader()
        for item in predictions:
            if item["gold_stance"] == item["predicted_stance"]:
                continue
            source = by_id[item["evidence_id"]]
            writer.writerow({
                "evidence_id": item["evidence_id"],
                "claim": source["claim"],
                "source_name": source["source_name"],
                "source_title": source["source_title"],
                "evidence_excerpt": source["evidence_excerpt"],
                "gold_stance": item["gold_stance"],
                "predicted_stance": item["predicted_stance"],
                "model_rationale": item["rationale"],
            })

    report_path = args.output_dir / "model_regression_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
