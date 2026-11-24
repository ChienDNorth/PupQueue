# Changelog
## v2.1.0
- Board: each column has its own background colour (Waitlist lavender, Ready blue, WIP amber, Completed green), matched to the light and dark themes.

## v2.0.0
- Task window: Enter finishes the field you are in instead of creating the task; Shift+Enter creates (or saves) the task. In Other information, Enter still starts a new line.
- Settings > Shortcuts: change both keys (click a shortcut, press the new keys). Saved in `settings.json` and checked by the server; each shortcut needs its own keys.
- Each open task card has a Mark done button. Clicking it starts a 7-second countdown bar; the task then moves to Completed. Clicking it again during the countdown cancels.
- Queue filters: a Show finished checkbox adds completed tasks to the list.

## v1.3.0
- Settings reorganised: categories on the left (General, Tasks, Storage, Settings file), one group of settings on the right.
- Every setting saves as soon as you change it; no Save button.
- Drawing types, social media choices and the title format are tag lists: type a name and press Enter to add, click a tag to rename it, x to remove it, drag to reorder.
- The priority list is no longer editable (Critical, High, Medium, Low, Lowest); the default priority is still a setting.
- Settings are kept in `settings.json` in the project folder, created on first start. Settings > Settings file shows its location and contents, downloads it, and loads a settings file (partial files are fine; invalid ones change nothing).
- Settings are validated on the server, so a hand-edited or uploaded file can't store bad values.
- Fix: two changes saved at the same moment could overwrite each other, and a page load could catch a settings or task file mid-save (on Windows a save could even fail). Saves and loads are now serialised and the settings file is written atomically.
- A broken hand-edited `settings.json` no longer stops the app; it runs on the defaults until the next save.
- Fix: the task form keeps a task's type or social media name even after it was removed from the lists.

## v1.2.0
- Fix: the theme you pick is saved the moment you pick it. Before, it was only a preview until Save, so the next reload (e.g. saving a task) reverted it to the system theme.
- Photos are saved as `task_records/photos/<task title>.png` (`_2`, `_3` for more) and renamed when the title changes.
- Each task's row in the CSV holds the address of its photos (`task_records/photos/<title>.png`, several separated by `;`; empty if none).
- Finishing a task keeps it in `completed.csv` and moves its photos to `task_records/photos/finished_task_photos/`; moving it back out of Completed moves them back.
- Deleting a task (finished or not), or removing one of its photos, deletes the file; an upload you cancel is removed too.
- On start, existing photos are renamed after their task and old partial addresses (`photos/x.png`) are rewritten as full ones.
- Settings > Storage: delete all finished-task photos at once.
- Task cards reorganised (title, chips, price/estimate/due, client, notes, thumbnails, actions); smaller buttons and one type scale across the pages; task counts on the toolbar and board columns.
- Language selector moved to the top right of every page.
- Snooze is a menu: 1 hour, 2 hours, 1 day, 2 days, 7 days, or custom; snoozed tasks get a Cancel snooze button (also in the detail panel).

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
