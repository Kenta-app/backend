-- Add missing columns to raw.news_raw table
ALTER TABLE raw.news_raw ADD COLUMN IF NOT EXISTS source_account VARCHAR(50);

-- Add missing columns to processed.news_processed table
-- Status can be: ok, error, duplicate
ALTER TABLE processed.news_processed ADD COLUMN IF NOT EXISTS status VARCHAR(50) NOT NULL DEFAULT 'ok';

-- Align summaries table with ORM expectations
ALTER TABLE processed.summaries
	ALTER COLUMN summary_text TYPE TEXT,
	ALTER COLUMN summary_text SET NOT NULL,
	ALTER COLUMN model_version SET NOT NULL;

-- Align ml_predictions table with ORM expectations
ALTER TABLE processed.ml_predictions
	ADD COLUMN IF NOT EXISTS fake_score NUMERIC(5,4) NOT NULL DEFAULT 0;

ALTER TABLE processed.ml_predictions
	ADD COLUMN IF NOT EXISTS fake_label VARCHAR(50),
	ADD COLUMN IF NOT EXISTS fake_bucket VARCHAR(20),
	ADD COLUMN IF NOT EXISTS raw_probabilities JSONB;

ALTER TABLE processed.ml_predictions
	ALTER COLUMN model_version TYPE TEXT,
	ALTER COLUMN model_version SET NOT NULL;
