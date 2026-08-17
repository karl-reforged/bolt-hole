-- Original production schema. Keep this migration immutable: later migrations
-- evolve it while preserving existing data.
CREATE TABLE IF NOT EXISTS notes (
  id TEXT PRIMARY KEY,
  property_id TEXT NOT NULL,
  author TEXT DEFAULT '',
  timestamp TEXT NOT NULL,
  note TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS properties (
  source_id TEXT PRIMARY KEY,
  suburb TEXT DEFAULT '',
  address TEXT DEFAULT '',
  first_seen TEXT,
  last_seen TEXT,
  status TEXT DEFAULT 'active',
  listing_url TEXT DEFAULT '',
  payload TEXT
);

CREATE TABLE IF NOT EXISTS reactions (
  property_id TEXT PRIMARY KEY,
  reaction TEXT NOT NULL,
  timestamp TEXT NOT NULL
);
