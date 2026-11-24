# PupQueue (翼犬稿单)
Commission queue tracker. Python stdlib only, no install.

    python pupqueue.py [port]     # opens http://127.0.0.1:8765
    python -c "import test_pupqueue as t; t.test_duration(); t.test_storage_and_api()"

- Data: `task records/active.csv`, `task records/completed.csv`, uploads in `photos/`, config in `settings.json` (all git-ignored).
- Languages: add `locales/<code>.json` (copy `en.json`); it shows up in Settings automatically.
- Pages: Queue (filters), Board (drag between Waitlist/Ready/WIP/Completed), Settings.

## Branches / versions
- `main` – released; `dev` – work in progress; features on `feature/<name>`. Tags `vX.Y.Z`.
- See CHANGELOG.md. Planned: Google Calendar sync (time spent + future plans).
