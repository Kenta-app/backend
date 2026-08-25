-- Guarda únicamente la URL de la imagen original; no almacena el archivo binario.
ALTER TABLE raw.news_raw
    ADD COLUMN IF NOT EXISTS image_url TEXT;

ALTER TABLE serving.news
    ADD COLUMN IF NOT EXISTS image_url TEXT;

-- Cuenta/handle usado por fuentes sociales como X; es distinto del nombre visible.
ALTER TABLE raw.source
    ADD COLUMN IF NOT EXISTS source_account VARCHAR(100);
