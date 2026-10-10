CREATE TABLE IF NOT EXISTS serving.draw_confirmations (
    draw_confirmation_id SERIAL PRIMARY KEY,
    draw_id VARCHAR(100) NOT NULL,
    user_id INTEGER NOT NULL REFERENCES serving.users(user_id),
    phone VARCHAR(32),
    confirmed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_draw_confirmation_user_draw
    ON serving.draw_confirmations (user_id, draw_id);

ALTER TABLE serving.draw_confirmations
    ALTER COLUMN phone DROP NOT NULL;
