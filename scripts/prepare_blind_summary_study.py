"""Prepare a reproducible, blinded BART-vs-mT5 human-evaluation payload.

This script reads only existing final-evaluation artifacts.  It never changes the
99 reference summaries or model predictions.  The JSON output deliberately keeps
the model mapping separate from the evaluator-facing workbooks.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

import pandas as pd


EXPECTED_MODELS = {
    "facebook/bart-large-cnn",
    "ELiRF/mt5-base-dacsa-es",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--references",
        type=Path,
        default=Path("output/paper_v7/human_summary_references_n99.csv"),
    )
    parser.add_argument(
        "--predictions",
        type=Path,
        default=Path("output/paper_v7/summarizer_benchmark_human_refs_n99.csv"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/paper_v7/blind_summary_study/blind_study_payload.json"),
    )
    parser.add_argument("--sample-size", type=int, default=30)
    parser.add_argument("--selection-seed", type=int, default=42)
    parser.add_argument("--assignment-seed", type=int, default=43)
    args = parser.parse_args()

    references = pd.read_csv(args.references)
    predictions = pd.read_csv(args.predictions)

    if references["id"].duplicated().any():
        raise ValueError("The reference file contains duplicate article IDs.")
    models = set(predictions["model"].unique())
    if models != EXPECTED_MODELS:
        raise ValueError(f"Unexpected model set: {sorted(models)}")

    by_id: dict[int, dict[str, str]] = defaultdict(dict)
    for row in predictions.itertuples(index=False):
        source_id = int(row.source_id)
        if row.model in by_id[source_id]:
            raise ValueError(f"Duplicate prediction for source_id={source_id}, model={row.model}")
        by_id[source_id][row.model] = str(row.prediction)

    ref_by_id = {int(row.id): row for row in references.itertuples(index=False)}
    eligible_ids = sorted(
        source_id
        for source_id, outputs in by_id.items()
        if source_id in ref_by_id and set(outputs) == EXPECTED_MODELS
    )
    if len(eligible_ids) != 99:
        raise ValueError(f"Expected 99 eligible paired cases; found {len(eligible_ids)}")
    if args.sample_size > len(eligible_ids):
        raise ValueError("Sample size exceeds eligible paired cases.")

    selection_rng = random.Random(args.selection_seed)
    selected_ids = selection_rng.sample(eligible_ids, args.sample_size)

    # Exact counterbalancing: in Salvador's workbook BART is A in half the items
    # (one additional item when n is odd); Jimena sees the inverse order per item.
    assignment_rng = random.Random(args.assignment_seed)
    bart_as_a = [True] * ((args.sample_size + 1) // 2) + [False] * (args.sample_size // 2)
    assignment_rng.shuffle(bart_as_a)

    records = []
    for position, (source_id, bart_is_a) in enumerate(zip(selected_ids, bart_as_a), start=1):
        ref = ref_by_id[source_id]
        outputs = by_id[source_id]
        records.append(
            {
                "case_id": f"C{position:02d}",
                "source_id": source_id,
                "title": str(ref.title),
                "url": str(ref.url),
                "article": str(ref.article),
                "salvador_mapping": {
                    "A": "facebook/bart-large-cnn" if bart_is_a else "ELiRF/mt5-base-dacsa-es",
                    "B": "ELiRF/mt5-base-dacsa-es" if bart_is_a else "facebook/bart-large-cnn",
                },
                "jimena_mapping": {
                    "A": "ELiRF/mt5-base-dacsa-es" if bart_is_a else "facebook/bart-large-cnn",
                    "B": "facebook/bart-large-cnn" if bart_is_a else "ELiRF/mt5-base-dacsa-es",
                },
                "outputs": outputs,
            }
        )

    payload = {
        "study": "Evaluación humana ciega: BART frente a mT5 para resúmenes en español",
        "population": "99 artículos con referencias humanas finales; dos sistemas por artículo",
        "sample_size": args.sample_size,
        "selection_seed": args.selection_seed,
        "assignment_seed": args.assignment_seed,
        "selection_method": "Muestra aleatoria simple sin reemplazo de los 99 casos emparejados elegibles.",
        "assignment_method": "Orden A/B contrabalanceado; Jimena observa el orden inverso al de Salvador en cada caso.",
        "cases": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {args.output} with {len(records)} blinded cases.")


if __name__ == "__main__":
    main()
