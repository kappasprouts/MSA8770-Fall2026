-- Idempotent authentication schema. The setup script hashes legacy passwords.
CREATE TABLE IF NOT EXISTS system_users (
  user_id varchar(20) PRIMARY KEY,
  full_name varchar(100) NOT NULL,
  email varchar(150) UNIQUE NOT NULL,
  role varchar(30) NOT NULL CHECK (role IN ('ADMISSIONS_OFFICER', 'DEAN', 'IT_SUPPORT')),
  is_active boolean DEFAULT true,
  created_at timestamptz DEFAULT now(),
  password text
);
ALTER TABLE system_users ADD COLUMN IF NOT EXISTS password_hash text;

CREATE TABLE IF NOT EXISTS auth_sessions (
  token_hash char(64) PRIMARY KEY,
  user_id varchar(20) NOT NULL REFERENCES system_users(user_id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS auth_sessions_expiry_idx ON auth_sessions(expires_at);

-- Persistent account throttling works across app restarts and multiple workers.
CREATE TABLE IF NOT EXISTS auth_login_attempts (
  account_key char(64) PRIMARY KEY,
  attempts integer NOT NULL DEFAULT 0,
  window_started_at timestamptz NOT NULL DEFAULT now()
);
