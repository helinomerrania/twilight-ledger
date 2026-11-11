-- SambaPOS backups the app has already looked at, so each one is read once.
-- SambaPOS writes one into its backup folder just before every reset, and the
-- app brings in any it has not seen by itself. A file is known by its name,
-- size and time; if any of them changes, it is read again.

CREATE TABLE pos_file (
  id         INTEGER PRIMARY KEY,
  name       TEXT    NOT NULL,
  size       INTEGER NOT NULL,
  modified   TEXT    NOT NULL,           -- the file's own time, as the PC shows it
  made_at    TEXT,                       -- when SambaPOS made it, from its name
  read_at    TEXT    NOT NULL DEFAULT (datetime('now')),
  ok         INTEGER NOT NULL CHECK (ok IN (0, 1)),
  note       TEXT,                       -- what came of it, or why it could not be read
  UNIQUE (name, size, modified)
);
