# Changelog
## v1.1.0
- Price currency choice: per task, with a default in Settings (USD for English, CNY for Chinese unless overridden).
- Estimated time is normalised when you finish typing (`90min` -> `1h30min`; no unit = minutes; also `1.5h`, `1d2h`, `1h30`, `1.5小时`).
- Due date uses a new calendar picker; time defaults to a full hour, set in Settings (default 12:00 AM).
- Add/Edit task window split into Title / Basic information / Time / Client information; priority moved to the top right as a signal-bar icon; click it (here or on any task card) to pick Critical / High / Medium / Low / Lowest.
- Client email is validated in the browser and on the server.
- Click a task to open a detail panel on the right (status can be changed there).
- Blue & white light theme and a dark blue theme, matched to the priority icon; pick in Settings (default: follow the system).
- Page scales with the window width so text stays readable on large monitors.
- Fix: reference photos now upload (Chinese file names broke the upload) and are stored in `task_records/photos/`.
- Data folder renamed `task records/` -> `task_records/` (existing data is moved automatically on start).
- Footer shows version and author.
- Fix: snooze times were stored in UTC but read as local time.

## v0.1.0 – V1 commission queue
Tasks (type, priority, price, paid details, estimate parsing, due, client contacts, notes, photos), snooze, filtered queue page, drag-and-drop board, CSV storage (active/completed), settings, en + zh locales.
Known limits: no CSV size rollover yet; no Google Calendar yet.
