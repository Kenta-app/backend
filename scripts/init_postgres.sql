-- =========================
-- CREACIÓN DE SCHEMAS
-- =========================
CREATE SCHEMA raw;
CREATE SCHEMA processed;
CREATE SCHEMA serving;

-- =========================
-- RAW LAYER
-- =========================
CREATE TABLE raw.source (
    source_id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    base_url VARCHAR(500) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    type VARCHAR(50) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE raw.ingestion_logs (
    log_id SERIAL PRIMARY KEY,
    ingestion_type VARCHAR(50) NOT NULL,
    status VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    source_id INT NOT NULL REFERENCES raw.source(source_id)
);

CREATE TABLE raw.news_raw (
    news_raw_id SERIAL PRIMARY KEY,
    source_id INT NOT NULL REFERENCES raw.source(source_id),
    log_id INT NOT NULL REFERENCES raw.ingestion_logs(log_id),
    platform VARCHAR(50) NOT NULL,
    source_acronym VARCHAR(50),
    original_url TEXT NOT NULL,
    title_raw TEXT NOT NULL,
    content_raw TEXT NOT NULL,
    author_raw VARCHAR(255),
    published_at TIMESTAMP,
    scraped_at TIMESTAMP,
    status VARCHAR(50)
);

-- =========================
-- PROCESSED LAYER
-- =========================
CREATE TABLE processed.news_processed (
    news_processed_id SERIAL PRIMARY KEY,
    news_raw_id INT NOT NULL REFERENCES raw.news_raw(news_raw_id),
    source_id INT NOT NULL REFERENCES raw.source(source_id),
    clean_text TEXT NOT NULL,
    language VARCHAR(10),
    token_count INT,
    processed_at TIMESTAMP NOT NULL
);

CREATE TABLE processed.processing_logs (
    log_id SERIAL PRIMARY KEY,
    news_processed_id INT NOT NULL REFERENCES processed.news_processed(news_processed_id),
    stage VARCHAR(50),
    status VARCHAR(50),
    message VARCHAR(150),
    created_at TIMESTAMP NOT NULL,
    model_version VARCHAR(50),
    execution_time_ms INT
);

CREATE TABLE processed.news_clusters (
    cluster_id SERIAL PRIMARY KEY,
    representative_news_processed INT NOT NULL REFERENCES processed.news_processed(news_processed_id),
    source_id INT NOT NULL REFERENCES raw.source(source_id),
    created_at TIMESTAMP NOT NULL,
    cluster_score DECIMAL(4,3)
);

CREATE TABLE processed.cluster_members (
    cluster_members_id SERIAL PRIMARY KEY,
    cluster_id INT NOT NULL REFERENCES processed.news_clusters(cluster_id),
    news_processed_id INT NOT NULL REFERENCES processed.news_processed(news_processed_id),
    source_id INT NOT NULL REFERENCES raw.source(source_id)
);

CREATE TABLE processed.ml_predictions (
    prediction_id SERIAL PRIMARY KEY,
    representative_news_processed INT NOT NULL REFERENCES processed.news_processed(news_processed_id),
    sentiment_label VARCHAR(20),
    sentiment_score DECIMAL(5,4) NOT NULL DEFAULT 0,
    model_version TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    fake_score DECIMAL(5,4) NOT NULL DEFAULT 0,
    fake_label VARCHAR(50),
    fake_bucket VARCHAR(20),
    raw_probabilities JSONB
);

CREATE TABLE processed.summaries (
    summary_id SERIAL PRIMARY KEY,
    representative_news_processed INT NOT NULL REFERENCES processed.news_processed(news_processed_id),
    summary_text TEXT NOT NULL,
    model_version VARCHAR(50) NOT NULL,
    created_at TIMESTAMP NOT NULL
);

-- =========================
-- SERVING LAYER
-- =========================
CREATE TABLE serving.users (
    user_id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50),
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE serving.news (
    news_id SERIAL PRIMARY KEY,
    representative_news_processed INT NOT NULL REFERENCES processed.news_processed(news_processed_id),
    source_id INT NOT NULL REFERENCES raw.source(source_id),
    title TEXT NOT NULL,
    summary TEXT,
    original_url TEXT,
    sentiment_label VARCHAR(20),
    sentiment_score DECIMAL(4,3),
    fake_score DECIMAL(4,3),
    published_at TIMESTAMP
);

CREATE TABLE serving.news_views (
    view_id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES serving.users(user_id),
    news_id INT NOT NULL REFERENCES serving.news(news_id),
    viewed_at TIMESTAMP NOT NULL,
    time_spent_sec INT
);

CREATE TABLE serving.news_click (
    click_id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES serving.users(user_id),
    news_id INT NOT NULL REFERENCES serving.news(news_id),
    clicked_at TIMESTAMP NOT NULL
);

CREATE TABLE serving.news_reactions (
    reaction_id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES serving.users(user_id),
    news_id INT NOT NULL REFERENCES serving.news(news_id),
    reaction INT,
    created_at TIMESTAMP NOT NULL
);

-- =========================
-- ÍNDICES ADICIONALES
-- =========================
CREATE INDEX idx_raw_source_url ON raw.news_raw(source_id, original_url);
CREATE INDEX idx_cluster_news ON processed.cluster_members(cluster_id, news_processed_id);
CREATE INDEX idx_user_news_reaction ON serving.news_reactions(user_id, news_id);
