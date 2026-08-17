-- Make the migrated production notes table match the declared/tested schema.
ALTER TABLE notes RENAME TO notes_legacy;

CREATE TABLE notes (
  id TEXT PRIMARY KEY,
  property_id TEXT NOT NULL,
  author TEXT NOT NULL,
  timestamp TEXT NOT NULL,
  note TEXT NOT NULL,
  FOREIGN KEY (property_id) REFERENCES properties(source_id) ON DELETE CASCADE
);

INSERT INTO notes (id, property_id, author, timestamp, note)
SELECT n.id,
       n.property_id,
       CASE WHEN n.author IS NULL OR trim(n.author) = '' THEN 'Legacy import' ELSE n.author END,
       n.timestamp,
       COALESCE(n.note, '')
FROM notes_legacy n
JOIN properties p ON p.source_id = n.property_id;

DROP TABLE notes_legacy;

CREATE INDEX notes_property_timestamp ON notes(property_id, timestamp);
