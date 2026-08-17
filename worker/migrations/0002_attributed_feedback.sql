-- Add attributable, participant-specific feedback without discarding data from
-- the original anonymous reaction table.
UPDATE notes SET author = 'Legacy import' WHERE author IS NULL OR trim(author) = '';
CREATE INDEX IF NOT EXISTS idx_notes_property_timestamp
  ON notes(property_id, timestamp);

ALTER TABLE reactions RENAME TO reactions_legacy;

CREATE TABLE reactions (
  property_id TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  author TEXT NOT NULL DEFAULT 'Anonymous',
  reaction TEXT NOT NULL CHECK (reaction IN ('love', 'interesting', 'pass')),
  timestamp TEXT NOT NULL,
  PRIMARY KEY (property_id, actor_id),
  FOREIGN KEY (property_id) REFERENCES properties(source_id) ON DELETE CASCADE
);

INSERT INTO reactions (property_id, actor_id, author, reaction, timestamp)
SELECT property_id, 'legacy-import', 'Legacy import', reaction, timestamp
FROM reactions_legacy
WHERE reaction IN ('love', 'interesting', 'pass');

DROP TABLE reactions_legacy;

CREATE TABLE favourites (
  property_id TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  author TEXT NOT NULL DEFAULT 'Anonymous',
  timestamp TEXT NOT NULL,
  PRIMARY KEY (property_id, actor_id),
  FOREIGN KEY (property_id) REFERENCES properties(source_id) ON DELETE CASCADE
);
