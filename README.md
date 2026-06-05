# Spanish-Peruvian Fake News Pipeline

This repository contains the code, preprocessing scripts, evaluation notes, and public release dataset used for a short-paper fake-news, stance, and summarization pipeline.

## Public Dataset

The public release keeps the curated claim-classification split:

- `data/claims_es_pe_full/train.tsv`
- `data/claims_es_pe_full/validation.tsv`
- `data/claims_es_pe_full/test.tsv`

Each row contains an internal id, binary label, claim text, source name, source URL, original label, and optional publication date. The split sizes are 2,372 train rows, 296 validation rows, and 298 test rows.

For summarization, the release includes metadata and synthetic reference summaries in `data/summary_references/synthetic_refs_30_fixed_metadata.csv`. Full article bodies are intentionally excluded from the public repository because they may be copyrighted by the original publishers.

## Third-Party Data

Some experiments use third-party corpora such as FNC-1 and fact-checking sources from Newtral, Maldita, and PeruCheck. Those raw files are not redistributed in the public release. Use the scripts in `scripts/` to rebuild local working data from the original sources where their terms allow it.

## Reproducibility

Install dependencies:

```bash
pip install -r requirements.txt
```

Useful scripts:

- `scripts/combine_claims.py`: build the final Spanish/Peruvian claim split.
- `scripts/prepare_fnc_stance_split.py`: create the grouped FNC-1 train/validation split.
- `scripts/generate_synthetic_summary_references.py`: generate synthetic summary references from local article text.
- `scripts/benchmark_summarizers.py`: evaluate summarizers against reference summaries.
- `scripts/evaluate_fakenews_model.py` and `scripts/evaluate_stance_model.py`: run classifier evaluation.

Benchmark results are summarized in `docs/benchmark_results.md`.

## Release And Citation

Recommended release flow:

1. Create a GitHub release, for example `v1.0-short-paper`.
2. Connect the repository to Zenodo and archive that release.
3. Cite the Zenodo DOI in the paper instead of citing only the GitHub URL.

## License

Code is released under the MIT License. Dataset metadata and labels in this repository are released under CC BY 4.0 where legally applicable. Third-party source text remains under the rights and terms of its original publishers.
