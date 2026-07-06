"""
Generate synthetic reference summaries for summarization benchmarking.

Use this to create silver-reference summaries with a model that is not one of
the summarizers being benchmarked. The output keeps the same columns as the
input and fills the summary field.
"""

from __future__ import annotations

import argparse
import csv
import os
import time
from pathlib import Path

import requests


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate synthetic summary references")
    parser.add_argument("--input", default="data/summary_references/candidates.csv")
    parser.add_argument("--output", default="data/summary_references/synthetic_refs.csv")
    parser.add_argument("--article_field", default="article")
    parser.add_argument("--summary_field", default="summary")
    parser.add_argument("--title_field", default="title")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--sleep_seconds", type=float, default=0.5)
    parser.add_argument("--model", default=os.getenv("OPENAI_SUMMARY_REFERENCE_MODEL", "gpt-4.1-mini"))
    parser.add_argument("--api_base", default=os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1/responses"))
    parser.add_argument("--max_article_chars", type=int, default=6000)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Regenerate rows that already have a summary.",
    )
    return parser


def build_prompt(title: str, article: str) -> str:
    return (
        "Genera un resumen de referencia para evaluar sistemas automaticos de resumen.\n"
        "Requisitos:\n"
        "- Espanol neutral y claro.\n"
        "- 2 a 4 oraciones.\n"
        "- No agregues informacion que no este en el texto.\n"
        "- Conserva actores, hecho principal, cifras importantes y contexto.\n"
        "- No incluyas opiniones ni frases introductorias.\n\n"
        f"Titulo: {title.strip()}\n\n"
        f"Texto:\n{article.strip()}"
    )


def extract_output_text(payload: dict) -> str:
    if payload.get("output_text"):
        return str(payload["output_text"]).strip()

    output_parts = payload.get("output", [])
    for item in output_parts:
        for content in item.get("content", []):
            text = content.get("text")
            if text:
                return str(text).strip()

    raise RuntimeError("No se pudo extraer texto de la respuesta del modelo.")


def call_responses_api(*, api_key: str, api_base: str, model: str, prompt: str) -> str:
    response = requests.post(
        api_base,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "input": prompt,
            "temperature": 0.2,
        },
        timeout=90,
    )
    response.raise_for_status()
    return extract_output_text(response.json())


def main() -> None:
    args = build_arg_parser().parse_args()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY no esta configurada.")

    input_path = Path(args.input)
    output_path = Path(args.output)
    if not input_path.exists():
        raise SystemExit(f"input not found: {input_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with input_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0].keys()) if rows else []

    if args.summary_field not in fieldnames:
        fieldnames.append(args.summary_field)

    generated = 0
    for index, row in enumerate(rows, start=1):
        if args.limit and generated >= args.limit:
            break
        if row.get(args.summary_field, "").strip() and not args.overwrite:
            continue

        article = str(row.get(args.article_field) or "").strip()
        if not article:
            continue
        title = str(row.get(args.title_field) or "").strip()
        prompt = build_prompt(title, article[: args.max_article_chars])
        summary = call_responses_api(
            api_key=api_key,
            api_base=args.api_base,
            model=args.model,
            prompt=prompt,
        )
        row[args.summary_field] = summary
        generated += 1
        print(f"Generated {generated}: row {index}, chars={len(summary)}")
        if args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved {generated} generated summaries to {output_path}")


if __name__ == "__main__":
    main()
