# Personal data lives in the repo

Tomorrow is a single-user tool. Defaults, Templates, Checklists, weather location, finished Plan HTML, and the live Session file (`data/session.json`) all live under the repo (e.g. `data/`, `plans/`) rather than a home-directory dotdir or a database. The Session file is gitignored — it stays on disk in the clone so an unfinished Session can resume, but it is tonight's scratch, not a versioned library.

**Why:** plain files stay editable in the same place as the code, easy to back up or sync with the repo, and match a thin v1 with no installer. The surprising part for a future reader is that cloning/sharing the repo can include personal routines — acceptable because this project is not published and not multi-user.

**Considered:** `~/.tomorrow/` (keeps the repo code-only; worse edit/sync story for a private personal project); SQLite (overkill until files hurt).
