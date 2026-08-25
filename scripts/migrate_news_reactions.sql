-- Agrega columnas faltantes en news_reactions (BD creada antes del modelo actualizado)
ALTER TABLE serving.news_reactions
    ADD COLUMN IF NOT EXISTS reaction INT;

ALTER TABLE serving.news_reactions
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW();
