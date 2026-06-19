import psycopg2

conn = psycopg2.connect('postgresql://postgres:admin@localhost:5432/Kenta')
cur = conn.cursor()

# Add source_account column to news_raw
cur.execute("ALTER TABLE raw.news_raw ADD COLUMN IF NOT EXISTS source_account VARCHAR(50)")

# Add status column to news_processed
cur.execute("ALTER TABLE processed.news_processed ADD COLUMN IF NOT EXISTS status VARCHAR(50) NOT NULL DEFAULT 'ok'")

# Align summaries table with ORM expectations
cur.execute("ALTER TABLE processed.summaries ALTER COLUMN summary_text TYPE TEXT")
cur.execute("ALTER TABLE processed.summaries ALTER COLUMN summary_text SET NOT NULL")
cur.execute("ALTER TABLE processed.summaries ALTER COLUMN model_version SET NOT NULL")

# Align ml_predictions table with ORM expectations
cur.execute("ALTER TABLE processed.ml_predictions ADD COLUMN IF NOT EXISTS fake_score NUMERIC(5,4) NOT NULL DEFAULT 0")
cur.execute("ALTER TABLE processed.ml_predictions ADD COLUMN IF NOT EXISTS fake_label VARCHAR(50)")
cur.execute("ALTER TABLE processed.ml_predictions ADD COLUMN IF NOT EXISTS fake_bucket VARCHAR(20)")
cur.execute("ALTER TABLE processed.ml_predictions ADD COLUMN IF NOT EXISTS raw_probabilities JSONB")
cur.execute("ALTER TABLE processed.ml_predictions ALTER COLUMN model_version TYPE TEXT")
cur.execute("ALTER TABLE processed.ml_predictions ALTER COLUMN model_version SET NOT NULL")

conn.commit()
print("Migration completed successfully")
cur.close()
conn.close()
