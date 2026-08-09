-- Bolt Hole backend schema — mirrors the Google Sheet tabs.
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
  payload TEXT  -- full property dict as JSON (shortlist.py reconstructs cards from it)
);

-- One row per property, last-writer-wins (matches Apps Script semantics).
CREATE TABLE IF NOT EXISTS reactions (
  property_id TEXT PRIMARY KEY,
  reaction TEXT NOT NULL,  -- love | interesting | pass
  timestamp TEXT NOT NULL
);
