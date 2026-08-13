"""Schema as an ordered list of forward-only migrations.

Never edit an existing entry — append a new one. `outreach_action` and `my_post`
are created now although nothing writes to them until M3/M4, so those milestones
never have to restructure a live database.
"""

_V1 = """
CREATE TABLE IF NOT EXISTS profile (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  place JSON NOT NULL,
  window_start DATE NOT NULL,
  window_end DATE NOT NULL,
  flexible BOOL NOT NULL DEFAULT 0,
  allow_split BOOL NOT NULL DEFAULT 1,
  max_split INT NOT NULL DEFAULT 3,
  price JSON NOT NULL,
  constraints JSON NOT NULL,
  templates JSON NOT NULL
);

CREATE TABLE IF NOT EXISTS source_config (
  id INTEGER PRIMARY KEY,
  profile_id INT NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
  platform TEXT NOT NULL,
  slug TEXT NOT NULL,
  name TEXT NOT NULL,
  method TEXT NOT NULL,
  rules JSON NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS post (
  id TEXT PRIMARY KEY,
  source TEXT,
  url TEXT,
  group_name TEXT,
  author_name TEXT,
  author_url TEXT,
  posted_at TEXT,
  text TEXT NOT NULL,
  first_seen TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS extraction (
  post_id TEXT PRIMARY KEY REFERENCES post(id) ON DELETE CASCADE,
  is_seeking BOOL,
  start_date DATE,
  end_date DATE,
  date_text TEXT,
  budget TEXT,
  confidence TEXT,
  model TEXT,
  error TEXT,
  extracted_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS enrichment (
  post_id TEXT PRIMARY KEY REFERENCES post(id) ON DELETE CASCADE,
  people_in_one_room INT,
  wants_multiple_rooms BOOL,
  gender TEXT,
  group_size INT,
  model TEXT,
  enriched_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS candidate (
  id INTEGER PRIMARY KEY,
  profile_id INT NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
  person_key TEXT NOT NULL,
  post_id TEXT NOT NULL REFERENCES post(id) ON DELETE CASCADE,
  also_posted_in JSON NOT NULL DEFAULT '[]',
  tier TEXT,
  tier_reason TEXT,
  fit TEXT,
  days_covered INT,
  wants_start DATE,
  wants_end DATE,
  status TEXT NOT NULL DEFAULT 'new',
  draft TEXT,
  first_seen TIMESTAMP NOT NULL,
  UNIQUE(profile_id, person_key)
);

CREATE TABLE IF NOT EXISTS outreach_action (
  id INTEGER PRIMARY KEY,
  profile_id INT NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
  candidate_id INT REFERENCES candidate(id) ON DELETE SET NULL,
  kind TEXT NOT NULL,
  text TEXT,
  status TEXT NOT NULL,
  sent_at TIMESTAMP,
  verified_at TIMESTAMP,
  error TEXT
);

CREATE TABLE IF NOT EXISTS my_post (
  id INTEGER PRIMARY KEY,
  profile_id INT NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
  source TEXT,
  group_name TEXT,
  permalink TEXT,
  status TEXT NOT NULL,
  blocked_reason TEXT,
  posted_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_candidate_profile_tier
  ON candidate(profile_id, tier, days_covered DESC);
CREATE INDEX IF NOT EXISTS idx_outreach_profile_kind_sent
  ON outreach_action(profile_id, kind, sent_at);
"""

MIGRATIONS: list[str] = [_V1]
