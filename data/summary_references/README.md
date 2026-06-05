# summary_references

Public metadata for the synthetic-reference summarization benchmark.

## Files

- `synthetic_refs_30_fixed_metadata.csv`: metadata-only public version with `id`, `title`, `url`, and `summary`.

The private working file used during benchmarking also contained full article text. That column is intentionally excluded from the public release because article bodies may be copyrighted by their original publishers.

To reproduce the benchmark, reconstruct article text locally from the original URLs where permitted, then use `scripts/generate_synthetic_summary_references.py` and `scripts/benchmark_summarizers.py`.
