# PupQueue (翼犬稿单)
Commission queue tracker. Python stdlib only, no install.

    python pupqueue.py [port]     # opens http://127.0.0.1:8765
    python -c "import test_pupqueue as t; [getattr(t, n)() for n in dir(t) if n.startswith('test_')]"

- Data (all git-ignored): `task_records/active.csv`, `task_records/completed.csv`, reference photos in `task_records/photos/` (named after the task title; finished tasks' photos in `task_records/photos/finished_task_photos/`), settings in `settings.json` (view, download or upload it under Settings > Settings file).
- Languages: add `locales/<code>.json` (copy `en.json`); it shows up in Settings automatically.
- Pages: Queue (filters), Board (drag between Waitlist/Ready/WIP/Completed), Settings.

## Branches / versions
- `main` – released; `dev` – work in progress; features on `feature/<name>`. Tags `vX.Y.Z`.
- See CHANGELOG.md. Planned: Google Calendar sync (time spent + future plans).
