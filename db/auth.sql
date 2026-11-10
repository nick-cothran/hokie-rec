-- Additive and rerunnable: preserves all existing people and sports data.
-- Enforce normalized uniqueness in the database, including concurrent sign-ups.
CREATE UNIQUE INDEX IF NOT EXISTS users_vt_pid_lower_key ON Users (LOWER(vt_pid));
CREATE UNIQUE INDEX IF NOT EXISTS users_email_lower_key ON Users (LOWER(email));

CREATE TABLE IF NOT EXISTS UserCredentials (
    user_id INT PRIMARY KEY REFERENCES Users(user_id) ON DELETE CASCADE,
    password_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS AuthSession (
    token_hash CHAR(64) PRIMARY KEY,
    user_id INT NOT NULL REFERENCES Users(user_id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS authsession_user_id_idx ON AuthSession(user_id);
CREATE INDEX IF NOT EXISTS authsession_expires_at_idx ON AuthSession(expires_at);

CREATE TABLE IF NOT EXISTS AuthLoginAttempt (
    identifier_hash CHAR(64) PRIMARY KEY,
    attempts INT NOT NULL,
    window_start TIMESTAMPTZ NOT NULL
);
