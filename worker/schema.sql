CREATE TABLE IF NOT EXISTS properties (
  source_id TEXT PRIMARY KEY,
  suburb TEXT DEFAULT '',
  address TEXT DEFAULT '',
  first_seen TEXT,
  last_seen TEXT,
  status TEXT DEFAULT 'active',
  listing_url TEXT DEFAULT '',
  payload TEXT  -- full property dict as JSON (shortlist.py reconstructs cards from it)
);

CREATE TABLE IF NOT EXISTS notes (
  id TEXT PRIMARY KEY,
  property_id TEXT NOT NULL,
  author TEXT NOT NULL,
  timestamp TEXT NOT NULL,
  note TEXT NOT NULL,
  FOREIGN KEY (property_id) REFERENCES properties(source_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS notes_property_timestamp
  ON notes(property_id, timestamp);

-- One reaction per participant and property.
CREATE TABLE IF NOT EXISTS reactions (
  property_id TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  author TEXT NOT NULL DEFAULT 'Anonymous',
  reaction TEXT NOT NULL CHECK (reaction IN ('love', 'interesting', 'pass')),
  timestamp TEXT NOT NULL,
  PRIMARY KEY (property_id, actor_id),
  FOREIGN KEY (property_id) REFERENCES properties(source_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS favourites (
  property_id TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  author TEXT NOT NULL DEFAULT 'Anonymous',
  timestamp TEXT NOT NULL,
  PRIMARY KEY (property_id, actor_id),
  FOREIGN KEY (property_id) REFERENCES properties(source_id) ON DELETE CASCADE
);
