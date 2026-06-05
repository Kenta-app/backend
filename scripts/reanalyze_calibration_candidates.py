"""
Reanalyze calibration candidates using the current pipeline and DB content.

Keeps manual labels and notes, updates analysis_* and top_claim_* fields.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db.database import SessionLocal
from app.ml.pipeline import news_analysis_pipeline
from app.processed.models import ProcessedNews
from app.raw.models import RawNews, Source
from app.serving.models import PublishedNews


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reanalyze a calibration CSV using the current pipeline."
    )
    parser.add_argument("--input", required=True, help="Existing labeled CSV.")
    parser.add_argument("--output", required=True, help="Destination CSV.")
    parser.add_argument("--limit", type=int, default=0, help="Analyze only the first N rows when greater than 0.")
    parser.add_argument(
        "--only-missing-db",
        action="store_true",
        help="Analyze only rows previously marked as missing_db_row.",
    )
    return parser


def analyze_record(title: str | None, content: str | None) -> dict:
    try:
        return news_analysis_pipeline.analyze_news(
            title=title,
            content=content,
            include_summary=False,
            allow_partial=True,
        )
    except Exception as exc:
        return {"error": str(exc)}


def first_claim(result: dict) -> dict | None:
    claims = ((result.get("fake_news") or {}).get("claims") or {}).get("items") or []
    return claims[0] if claims else None


def fetch_rows_by_ids(db, ids: list[int]):
    if not ids:
        return []
    return (
        db.query(ProcessedNews, RawNews, Source, PublishedNews)
        .join(RawNews, RawNews.news_raw_id == ProcessedNews.news_raw_id)
        .join(Source, Source.source_id == ProcessedNews.source_id)
        .outerjoin(
            PublishedNews,
            PublishedNews.representative_news_processed_id == ProcessedNews.news_processed_id,
        )
        .filter(ProcessedNews.news_processed_id.in_(ids))
        .all()
    )


def extract_text_from_csv_row(row: dict[str, str]) -> tuple[str | None, str | None]:
    title = first_present(
        row,
        "title",
        "top_claim_model_input",
        "top_claim_text",
        "top_claim_target",
    )
    content = first_present(
        row,
        "content",
        "clean_text",
        "body",
        "top_claim_model_input",
        "top_claim_text",
        "top_claim_target",
    )
    if content == title:
        content = None
    return title, content


def first_present(row: dict[str, str], *columns: str) -> str | None:
    for column in columns:
        value = (row.get(column) or "").strip()
        if value:
            return value
    return None


def update_row_from_result(row: dict[str, str], result: dict) -> dict[str, str]:
    fake_news = result.get("fake_news") or {}
    claim = first_claim(result or {})
    claim_prediction = (claim or {}).get("prediction") or {}
    claim_probabilities = claim_prediction.get("probabilities") or {}

    warnings = " | ".join(result.get("warnings") or []) if result else ""
    error = result.get("error", "") if result else ""

    updated = dict(row)
    updated["analysis_risk_score"] = (
        f"{float(fake_news.get('risk_score')):.4f}"
        if fake_news.get("risk_score") is not None
        else ""
    )
    updated["analysis_triage_label"] = fake_news.get("triage_label") or ""
    updated["analysis_triage_display"] = fake_news.get("triage_display") or ""
    updated["analysis_fake_label"] = fake_news.get("label") or ""
    updated["analysis_claim_based"] = str(bool(fake_news.get("claim_based")))
    updated["top_claim_text"] = (claim or {}).get("text") or ""
    updated["top_claim_target"] = (claim or {}).get("stance_target") or ""
    updated["top_claim_model_input"] = (claim or {}).get("model_input") or ""
    updated["top_claim_mode"] = (claim or {}).get("extraction_mode") or ""
    updated["top_claim_quality"] = (claim or {}).get("quality") or ""
    updated["top_claim_quality_reasons"] = " | ".join(
        (claim or {}).get("quality_reasons") or []
    )
    updated["top_claim_label"] = claim_prediction.get("label") or ""
    updated["top_claim_p_false"] = (
        f"{float(claim_probabilities.get('False')):.4f}"
        if claim_probabilities.get("False") is not None
        else ""
    )
    updated["warnings"] = warnings
    updated["error"] = error
    return updated


def update_row_from_db(row: dict[str, str], db_row) -> dict[str, str]:
    processed, raw_news, source, published = db_row
    result = analyze_record(raw_news.title_raw, processed.clean_text)
    return update_row_from_result(row, result)


def update_row_from_csv(row: dict[str, str]) -> dict[str, str]:
    title, content = extract_text_from_csv_row(row)
    if not title and not content:
        updated = dict(row)
        updated["error"] = "missing_text"
        return updated
    result = analyze_record(title, content)
    return update_row_from_result(row, result)


def main() -> int:
    args = build_parser().parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)

    with input_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = reader.fieldnames or []

    if args.only_missing_db:
        rows = [
            row
            for row in rows
            if (row.get("error") or "").strip() == "missing_db_row"
        ]

    if args.limit > 0:
        rows = rows[: args.limit]

    ids: list[int] = []
    for row in rows:
        value = (row.get("representative_id") or "").strip()
        if not value:
            continue
        try:
            ids.append(int(value))
        except ValueError:
            continue

    db = SessionLocal()
    try:
        db_rows = fetch_rows_by_ids(db, ids)
        db_map = {
            int(processed.news_processed_id): (processed, raw_news, source, published)
            for processed, raw_news, source, published in db_rows
        }

        updated_rows: list[dict[str, str]] = []
        missing = 0
        updated_from_db = 0
        updated_from_csv = 0
        for row in rows:
            value = (row.get("representative_id") or "").strip()
            rep_id = None
            if value:
                try:
                    rep_id = int(value)
                except ValueError:
                    rep_id = None

            if rep_id is None or rep_id not in db_map:
                updated = update_row_from_csv(row)
                if updated.get("error") == "missing_text":
                    missing += 1
                else:
                    updated_from_csv += 1
                updated_rows.append(updated)
                continue

            updated_rows.append(update_row_from_db(row, db_map[rep_id]))
            updated_from_db += 1

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(updated_rows)

        print(f"Updated {len(updated_rows)} rows.")
        print(f"  from DB rows : {updated_from_db}")
        print(f"  from CSV text: {updated_from_csv}")
        if missing:
            print(f"  missing text : {missing}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
