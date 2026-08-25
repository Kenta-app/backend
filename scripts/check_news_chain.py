#!/usr/bin/env python3
from dotenv import load_dotenv

load_dotenv()

from app.db.database import SessionLocal
from app.processed.models import MlPrediction, ProcessedNews
from app.raw.models import RawNews

db = SessionLocal()

print("=== raw.news_raw ===")
for row in db.query(RawNews).all():
    title = (row.title_raw or "")[:80]
    print(f"  id={row.news_raw_id} | title={title}")
    print(f"    content_len={len(row.content_raw or '')} | url={row.original_url}")

print("\n=== processed.news_processed ===")
for row in db.query(ProcessedNews).all():
    print(
        f"  id={row.news_processed_id} | raw_id={row.news_raw_id} "
        f"| clean_len={len(row.clean_text or '')}"
    )

print("\n=== processed.ml_predictions ===")
for row in db.query(MlPrediction).all():
    print(
        f"  id={row.prediction_id} | processed_id={row.representative_news_processed_id} "
        f"| fake={row.fake_score} | sentiment={row.sentiment_label}"
    )

db.close()
