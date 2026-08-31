"""Create evaluator-safe payload from the fixed deployed-model benchmark."""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

import pandas as pd


MODELS = {"facebook/bart-large-cnn", "ELiRF/mt5-base-dacsa-es"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("output/paper_v7/deployment_summary_evaluation/input_unseen_n30.csv"),
    )
    parser.add_argument(
        "--benchmark",
        type=Path,
        default=Path("output/paper_v7/deployment_summary_evaluation/benchmark_deployed_n30.csv"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/paper_v7/deployment_summary_evaluation/blind_study_payload.json"),
    )
    parser.add_argument("--assignment-seed", type=int, default=45)
    args = parser.parse_args()

    inputs = pd.read_csv(args.input)
    predictions = pd.read_csv(args.benchmark)
    if set(predictions["model"].unique()) != MODELS:
        raise ValueError("The benchmark must contain exactly BART and mT5 outputs.")
    if inputs["id"].duplicated().any():
        raise ValueError("The fixed input has duplicate source IDs.")

    by_id: dict[int, dict[str, str]] = defaultdict(dict)
    for row in predictions.itertuples(index=False):
        source_id = int(row.source_id)
        if row.model in by_id[source_id]:
            raise ValueError(f"Duplicate output for source ID {source_id}.")
        by_id[source_id][row.model] = str(row.prediction)
    selected_ids = inputs["id"].astype(int).tolist()
    if any(set(by_id[source_id]) != MODELS for source_id in selected_ids):
        raise ValueError("Every selected source needs one output from each model.")

    assignment_rng = random.Random(args.assignment_seed)
    bart_as_a = [True] * ((len(selected_ids) + 1) // 2) + [False] * (len(selected_ids) // 2)
    assignment_rng.shuffle(bart_as_a)
    cases = []
    for position, (row, bart_is_a) in enumerate(zip(inputs.itertuples(index=False), bart_as_a), start=1):
        source_id = int(row.id)
        cases.append(
            {
                "case_id": f"D{position:02d}",
                "source_id": source_id,
                "title": str(row.title),
                "url": str(row.url),
                "article": str(row.article),
                "salvador_mapping": {
                    "A": "facebook/bart-large-cnn" if bart_is_a else "ELiRF/mt5-base-dacsa-es",
                    "B": "ELiRF/mt5-base-dacsa-es" if bart_is_a else "facebook/bart-large-cnn",
                },
                "jimena_mapping": {
                    "A": "ELiRF/mt5-base-dacsa-es" if bart_is_a else "facebook/bart-large-cnn",
                    "B": "facebook/bart-large-cnn" if bart_is_a else "ELiRF/mt5-base-dacsa-es",
                },
                "outputs": by_id[source_id],
            }
        )
    payload = {
        "study": "Follow-up blinded evaluation of deployed BART post-processing versus mT5.",
        "population": "30 randomly sampled articles not used in the previous raw-output human evaluation.",
        "sample_size": len(cases),
        "selection_seed": 44,
        "assignment_seed": args.assignment_seed,
        "selection_method": "Simple random sample without replacement from the 69 articles not previously annotated.",
        "assignment_method": "A/B order counterbalanced; Jimena sees the inverse candidate order for every item.",
        "generation_config": {
            "max_input_length": 1024,
            "max_summary_length": 150,
            "min_summary_length": 60,
            "num_beams": 4,
            "length_penalty": 1.5,
            "no_repeat_ngram_size": 3,
            "deployment_postprocessing": True,
        },
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(cases)} fresh, blinded cases to {args.output}.")


if __name__ == "__main__":
    main()
