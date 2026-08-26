-- Existing users remain valid; the registration API requires both fields for new accounts.
ALTER TABLE serving.users
    ADD COLUMN IF NOT EXISTS birth_date DATE;

ALTER TABLE serving.users
    ADD COLUMN IF NOT EXISTS gender VARCHAR(50);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_unique
    ON serving.users (username);
