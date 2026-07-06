"""
Benchmark seq2seq summarizers against reference summaries.

The input can be a CSV/JSONL file with article and reference summary fields,
or the local database summaries table via --from_db. Database summaries are
useful as a pseudo-reference only; for thesis reporting, prefer a hand-reviewed
sample or source-provided summaries.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


TOKEN_RE = re.compile(r"\w+", flags=re.UNICODE)


@dataclass(frozen=True)
class SummaryExample:
    article: str
    reference: str
    source_id: str | None = None


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark summarization models")
    parser.add_argument(
        "--models",
        nargs="+",
        default=[os.getenv("SUMMARIZER_MODEL_NAME", "facebook/bart-large-cnn")],
        help="One or more Hugging Face model names or local directories.",
    )
    parser.add_argument("--input", default=None, help="CSV or JSONL input file.")
    parser.add_argument("--format", choices=("auto", "csv", "jsonl"), default="auto")
    parser.add_argument("--article_field", default="article")
    parser.add_argument("--reference_field", default="summary")
    parser.add_argument("--id_field", default="id")
    parser.add_argument("--from_db", action="store_true")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--min_article_chars", type=int, default=700)
    parser.add_argument("--max_input_length", type=int, default=1024)
    parser.add_argument("--max_summary_length", type=int, default=120)
    parser.add_argument("--min_summary_length", type=int, default=40)
    parser.add_argument("--num_beams", type=int, default=4)
    parser.add_argument("--output_json", default="output/summarizer_benchmark.json")
    parser.add_argument("--output_csv", default="output/summarizer_benchmark.csv")
    return parser


def normalize_tokens(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text or "")]


def ngrams(tokens: list[str], n: int) -> list[tuple[str, ...]]:
    if len(tokens) < n:
        return []
    return [tuple(tokens[index : index + n]) for index in range(len(tokens) - n + 1)]


def f1_score(overlap: int, predicted_total: int, reference_total: int) -> float:
    if predicted_total <= 0 or reference_total <= 0 or overlap <= 0:
        return 0.0
    precision = overlap / predicted_total
    recall = overlap / reference_total
    return 2 * precision * recall / (precision + recall)


def overlap_count(predicted: list[tuple[str, ...]], reference: list[tuple[str, ...]]) -> int:
    remaining: dict[tuple[str, ...], int] = {}
    for item in reference:
        remaining[item] = remaining.get(item, 0) + 1
    count = 0
    for item in predicted:
        if remaining.get(item, 0) > 0:
            count += 1
            remaining[item] -= 1
    return count


def lcs_length(a: list[str], b: list[str]) -> int:
    if not a or not b:
        return 0
    previous = [0] * (len(b) + 1)
    for token_a in a:
        current = [0] * (len(b) + 1)
        for index_b, token_b in enumerate(b, start=1):
            if token_a == token_b:
                current[index_b] = previous[index_b - 1] + 1
            else:
                current[index_b] = max(previous[index_b], current[index_b - 1])
        previous = current
    return previous[-1]


def rouge_scores(predicted_text: str, reference_text: str) -> dict[str, float]:
    predicted_tokens = normalize_tokens(predicted_text)
    reference_tokens = normalize_tokens(reference_text)

    predicted_unigrams = ngrams(predicted_tokens, 1)
    reference_unigrams = ngrams(reference_tokens, 1)
    predicted_bigrams = ngrams(predicted_tokens, 2)
    reference_bigrams = ngrams(reference_tokens, 2)

    rouge1 = f1_score(
        overlap_count(predicted_unigrams, reference_unigrams),
        len(predicted_unigrams),
        len(reference_unigrams),
    )
    rouge2 = f1_score(
        overlap_count(predicted_bigrams, reference_bigrams),
        len(predicted_bigrams),
        len(reference_bigrams),
    )
    rouge_l = f1_score(
        lcs_length(predicted_tokens, reference_tokens),
        len(predicted_tokens),
        len(reference_tokens),
    )
    return {"rouge1_f1": rouge1, "rouge2_f1": rouge2, "rougeL_f1": rouge_l}


def read_file_examples(args: argparse.Namespace) -> list[SummaryExample]:
    if not args.input:
        raise SystemExit("--input is required unless --from_db is used")

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"input not found: {input_path}")

    file_format = args.format
    if file_format == "auto":
        file_format = "jsonl" if input_path.suffix.lower() == ".jsonl" else "csv"

    examples: list[SummaryExample] = []
    if file_format == "jsonl":
        with input_path.open("r", encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
    else:
        with input_path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))

    for row in rows:
        article = str(row.get(args.article_field) or "").strip()
        reference = str(row.get(args.reference_field) or "").strip()
        if len(article) < args.min_article_chars or not reference:
            continue
        examples.append(
            SummaryExample(
                article=article,
                reference=reference,
                source_id=str(row.get(args.id_field) or len(examples) + 1),
            )
        )
        if args.limit and len(examples) >= args.limit:
            break
    return examples


def read_db_examples(args: argparse.Namespace) -> list[SummaryExample]:
    from sqlalchemy import text

    from app.db.database import SessionLocal

    query = text(
        """
        select
            p.news_processed_id as id,
            p.clean_text as article,
            s.summary_text as reference
        from processed.news_processed p
        join processed.summaries s
          on s.representative_news_processed = p.news_processed_id
        where length(coalesce(p.clean_text, '')) >= :min_chars
          and length(coalesce(s.summary_text, '')) >= 20
        order by p.news_processed_id
        limit :limit
        """
    )
    db = SessionLocal()
    try:
        rows = db.execute(
            query,
            {"min_chars": args.min_article_chars, "limit": max(args.limit, 1)},
        ).mappings()
        return [
            SummaryExample(
                article=str(row["article"]),
                reference=str(row["reference"]),
                source_id=str(row["id"]),
            )
            for row in rows
        ]
    finally:
        db.close()


def load_examples(args: argparse.Namespace) -> list[SummaryExample]:
    examples = read_db_examples(args) if args.from_db else read_file_examples(args)
    if not examples:
        raise SystemExit("No benchmark examples were found.")
    return examples


def summarize(model_name: str, examples: list[SummaryExample], args: argparse.Namespace, device: torch.device) -> list[dict]:
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
    model.to(device)
    model.eval()

    encoder_max_length = getattr(model.config, "max_position_embeddings", None)
    if encoder_max_length is None and hasattr(model.config, "encoder"):
        encoder_max_length = getattr(model.config.encoder, "max_position_embeddings", None)
    tokenizer_max_length = getattr(tokenizer, "model_max_length", None)
    safe_max_input_length = args.max_input_length
    for candidate in (encoder_max_length, tokenizer_max_length):
        if isinstance(candidate, int) and candidate > 0:
            safe_max_input_length = min(safe_max_input_length, candidate)

    rows: list[dict] = []
    for index, example in enumerate(examples, start=1):
        started = perf_counter()
        inputs = tokenizer(
            example.article,
            return_tensors="pt",
            max_length=safe_max_input_length,
            truncation=True,
        ).to(device)
        with torch.no_grad():
            output_ids = model.generate(
                inputs["input_ids"],
                attention_mask=inputs.get("attention_mask"),
                num_beams=args.num_beams,
                max_length=args.max_summary_length,
                min_length=args.min_summary_length,
                no_repeat_ngram_size=3,
                length_penalty=1.5,
                early_stopping=True,
            )
        prediction = tokenizer.decode(output_ids[0], skip_special_tokens=True)
        elapsed_ms = int((perf_counter() - started) * 1000)
        metrics = rouge_scores(prediction, example.reference)
        rows.append(
            {
                "model": model_name,
                "example_index": index,
                "source_id": example.source_id,
                "elapsed_ms": elapsed_ms,
                "reference": example.reference,
                "prediction": prediction,
                **metrics,
            }
        )
        print(
            f"{model_name} example {index}/{len(examples)} "
            f"rougeL={metrics['rougeL_f1']:.4f} elapsed_ms={elapsed_ms}"
        )
    return rows


def aggregate(rows: list[dict]) -> list[dict]:
    by_model: dict[str, list[dict]] = {}
    for row in rows:
        by_model.setdefault(row["model"], []).append(row)

    summary: list[dict] = []
    for model_name, model_rows in by_model.items():
        count = len(model_rows)
        summary.append(
            {
                "model": model_name,
                "examples": count,
                "avg_rouge1_f1": sum(row["rouge1_f1"] for row in model_rows) / count,
                "avg_rouge2_f1": sum(row["rouge2_f1"] for row in model_rows) / count,
                "avg_rougeL_f1": sum(row["rougeL_f1"] for row in model_rows) / count,
                "avg_elapsed_ms": sum(row["elapsed_ms"] for row in model_rows) / count,
            }
        )
    return sorted(summary, key=lambda item: item["avg_rougeL_f1"], reverse=True)


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "model",
        "example_index",
        "source_id",
        "elapsed_ms",
        "rouge1_f1",
        "rouge2_f1",
        "rougeL_f1",
        "reference",
        "prediction",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = build_arg_parser().parse_args()
    examples = load_examples(args)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    all_rows: list[dict] = []
    for model_name in args.models:
        all_rows.extend(summarize(model_name, examples, args, device))

    summary = aggregate(all_rows)
    payload = {
        "run_date": datetime.now().date().isoformat(),
        "reference_source": "database_summaries" if args.from_db else str(args.input),
        "example_count": len(examples),
        "metrics_note": "Lexical ROUGE-style F1 implemented locally.",
        "summary": summary,
        "rows": all_rows,
    }

    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    with output_json.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2)

    if args.output_csv:
        write_csv(Path(args.output_csv), all_rows)

    print("Summarizer benchmark summary")
    for item in summary:
        print(
            f"  {item['model']}: rougeL={item['avg_rougeL_f1']:.4f} "
            f"rouge1={item['avg_rouge1_f1']:.4f} "
            f"avg_elapsed_ms={item['avg_elapsed_ms']:.0f}"
        )


if __name__ == "__main__":
    main()
