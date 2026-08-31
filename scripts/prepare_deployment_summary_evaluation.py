"""Select a fresh, reproducible human-evaluation sample for deployed summarizers."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--references",
        type=Path,
        default=Path("output/paper_v7/human_summary_references_n99.csv"),
    )
    parser.add_argument(
        "--previous-study",
        type=Path,
        default=Path("output/paper_v7/blind_summary_study/blind_study_payload.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/paper_v7/deployment_summary_evaluation"),
    )
    parser.add_argument("--sample-size", type=int, default=30)
    parser.add_argument("--seed", type=int, default=44)
    args = parser.parse_args()

    references = pd.read_csv(args.references)
    previous = json.loads(args.previous_study.read_text(encoding="utf-8"))
    previously_annotated = {int(case["source_id"]) for case in previous["cases"]}
    eligible = references.loc[~references["id"].isin(previously_annotated)].copy()
    if len(eligible) < args.sample_size:
        raise ValueError("Not enough articles remain after excluding the first human evaluation.")

    selected_ids = random.Random(args.seed).sample(eligible["id"].astype(int).tolist(), args.sample_size)
    selected = eligible.set_index("id").loc[selected_ids].reset_index()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    selected.to_csv(args.output_dir / "input_unseen_n30.csv", index=False, encoding="utf-8")
    manifest = {
        "purpose": "Follow-up blinded evaluation of deployed BART post-processing versus mT5.",
        "population": "99 final human-reference articles; 30 articles from the earlier raw-output study excluded.",
        "eligible_count": len(eligible),
        "sample_size": args.sample_size,
        "selection_seed": args.seed,
        "selection_method": "Simple random sample without replacement.",
        "selected_source_ids": selected_ids,
        "fixed_generation_config": {
            "max_input_length": 1024,
            "max_summary_length": 150,
            "min_summary_length": 60,
            "num_beams": 4,
            "length_penalty": 1.5,
            "no_repeat_ngram_size": 3,
        },
    }
    (args.output_dir / "selection_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Saved {len(selected)} unseen cases with seed={args.seed}.")


if __name__ == "__main__":
    main()
