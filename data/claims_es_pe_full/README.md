# claims_es_pe_full

Curated Spanish claim-classification dataset focused on Spanish-language and Peruvian fact-checking use cases.

## Files

- `train.tsv`: 2,372 rows
- `validation.tsv`: 296 rows
- `test.tsv`: 298 rows

## Format

Tab-separated rows without a header:

1. `id`: split-local integer identifier
2. `binary_label`: `true` or `false`
3. `claim`: checked claim text
4. `source`: source dataset or fact-checking outlet
5. `url`: original source URL
6. `original_label`: original verdict label
7. `published_at`: optional source publication timestamp

## Redistribution Note

The dataset includes claim-level text, labels, source names, URLs, and metadata. It does not include full third-party article bodies. Users should consult the original source URLs and source terms before redistributing or extending the underlying text.
