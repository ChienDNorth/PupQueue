"""PupQueue - commission queue tracker. Stdlib only. Run: python pupqueue.py [port]"""
import csv, json, math, mimetypes, re, shutil, sys, threading, uuid, webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

VERSION, AUTHOR, YEAR = "2.2.0", "北原啸ChienDNorth", 2026
ROOT = Path(__file__).parent
RECORDS = ROOT / "task_records"
PHOTOS = RECORDS / "photos"
SETTINGS_FILE = ROOT / "settings.json"
FIELDS = ["id", "title", "type", "priority", "price", "currency", "paid", "paid_amount", "paid_time",
          "estimate_min", "due", "client_name", "client_email", "client_socials",
          "notes", "photos", "status", "snoozed_until", "snoozed_from", "created"]  # snoozed_from: status to return to when the snooze ends
STATUSES = ["Waitlist", "Ready", "WIP", "Completed"]
PRIORITIES = ["Critical", "High", "Medium", "Low", "Lowest"]  # fixed, highest first; the icon shows one bar per level
TITLE_PARTS = ["type", "social", "title", "price", "paid"]
DEFAULT_SETTINGS = {
    "language": "en",
    "types": ["Gift", "Self Project", "Drawing Swap", "Commission", "Else"],
    "default_priority": "Medium",
    "socials": ["QQ", "Twitter", "Vgen", "Mihuashi"],
    "currency": "",  # "" = follow the language (en -> USD, zh -> CNY, see locales/*.json)
    "theme": "auto",  # auto = follow the system, or light / dark
    "default_due_time": "00:00",  # time of day filled in when a due date is picked
    "title_order": list(TITLE_PARTS),  # parts of the displayed title, in order
    "shortcuts": {"save_task": "Shift+Enter", "finish_field": "Enter"},  # keys in the task window, written like the page records them
}
SHORTCUT_RE = re.compile(r"((Ctrl|Alt|Shift|Meta)\+)*[^\s+]{1,20}")
FINISHED_DIR = "finished_task_photos"  # inside the photos folder
RESERVED_NAME = re.compile(r"CON|PRN|AUX|NUL|COM\d|LPT\d")
DATA_LOCK = threading.Lock()  # requests run in threads: writes must not interleave, and nobody may read a file while it is replaced (Windows refuses)
IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "avif", "heic"}
UNITS = {**dict.fromkeys(("min", "mins", "minute", "minutes", "m", "分", "分钟"), 1),
         **dict.fromkeys(("h", "hr", "hrs", "hour", "hours", "时", "小时"), 60),
         **dict.fromkeys(("d", "day", "days", "天", "日"), 1440)}
_ATOM = r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
EMAIL_RE = re.compile(rf"{_ATOM}(?:\.{_ATOM})*@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{{0,61}}[A-Za-z0-9])?\.)+[A-Za-z]{{2,}}")


def parse_duration(text):
    """'70min'->70, '0.5h'->30, '1d2h'->1560, '1h30'->90; a bare number means minutes. '' -> ''."""
    text = re.sub(r"[\s,]", "", str(text).lower())
    if not text:
        return ""
    toks = re.findall(r"(\d+(?:\.\d+)?)([^\d.]*)", text)
    if not toks or "".join(n + u for n, u in toks) != text:
        raise ValueError("invalid_estimate")
    total = 0
    for i, (n, u) in enumerate(toks):
        if u in UNITS:
            total += float(n) * UNITS[u]
        elif u == "" and i == len(toks) - 1:
            total += float(n)  # unit omitted -> minutes
        else:
            raise ValueError("invalid_estimate")
    return round(total)


def format_duration(minutes):
    if minutes in ("", None):
        return ""
    d, rest = divmod(int(minutes), 1440)
    h, m = divmod(rest, 60)
    return "".join(f"{v}{u}" for v, u in ((d, "d"), (h, "h"), (m, "min")) if v) or "0min"


def migrate():
    """Move data from the V1 layout ('task records/', photos/) into task_records/, and tidy existing photos."""
    old = ROOT / "task records"
    if old.is_dir() and not RECORDS.exists():
        old.rename(RECORDS)
    old_photos = ROOT / "photos"
    if old_photos.is_dir():
        PHOTOS.mkdir(parents=True, exist_ok=True)
        for f in old_photos.iterdir():
            shutil.move(str(f), PHOTOS / f.name)
        old_photos.rmdir()
    tasks = load_tasks()  # bring existing photos in line: named after the task, full address in the CSV
    stored = [t["photos"] for t in tasks]
    for t in tasks:
        organize_photos(t)
    if [t["photos"] for t in tasks] != stored:
        save_tasks(tasks)


def norm_photo(rel):
    return rel if rel.startswith(RECORDS.name + "/") else f"{RECORDS.name}/{rel}"  # early V1.2 rows held 'photos/x.png'


def photo_list(t):
    return [norm_photo(p) for p in (t["photos"] if t else "").split(";") if p]


def photo_file(rel):
    """Existing file for a stored address like 'task_records/photos/a.png'; None if missing or outside the photos folder."""
    p = (RECORDS.parent / norm_photo(rel)).resolve()
    return p if p.is_relative_to(PHOTOS.resolve()) and p.is_file() else None


def photo_rel(p):
    """The address kept in the CSV: the photo's path from the project folder, e.g. task_records/photos/Title.png."""
    return p.relative_to(RECORDS.parent.resolve()).as_posix()


def photo_stem(title):
    s = re.sub(r'[\\/:*?"<>|;%#\x00-\x1f]', "_", title).strip(" .")[:60].strip(" .")
    return (s or "task") + "_" if not s or RESERVED_NAME.fullmatch(s.upper()) else s


def free_path(folder, stem, suffix):
    n = 1
    while (dst := folder / f"{stem}{'' if n == 1 else f'_{n}'}{suffix}").exists():
        n += 1
    return dst


def organize_photos(t):
    """Name photos after the task title (title.png, title_2.png, ...); completed tasks keep them in photos/finished_task_photos/."""
    folder = (PHOTOS / FINISHED_DIR if t["status"] == "Completed" else PHOTOS).resolve()
    stem, kept = photo_stem(t["title"]), []
    for rel in photo_list(t):
        src = photo_file(rel)
        if not src or src in kept:
            continue  # missing file or duplicate reference
        if src.parent != folder or not re.fullmatch(re.escape(stem) + r"(_\d+)?", src.stem):
            folder.mkdir(parents=True, exist_ok=True)
            dst = free_path(folder, stem, src.suffix)
            src.rename(dst)
            src = dst
        kept.append(src)
    t["photos"] = ";".join(photo_rel(p) for p in kept)


def discard_photo(rel):
    if src := photo_file(rel):
        src.unlink()


def finished_photos():
    d = PHOTOS / FINISHED_DIR
    return [f for f in d.iterdir() if f.is_file()] if d.is_dir() else []


def clear_finished_photos():
    files = finished_photos()
    out = {"deleted": len(files), "bytes": sum(f.stat().st_size for f in files)}
    gone = {photo_rel(f.resolve()) for f in files}
    for f in files:
        f.unlink()
    tasks = load_tasks()
    for t in tasks:  # leave no dangling references in the completed tasks
        t["photos"] = ";".join(p for p in photo_list(t) if p not in gone)
    save_tasks(tasks)
    return out


def delete_unsaved_photo(name):
    """Remove an uploaded photo that no task references (dialog cancelled / thumbnail removed before saving)."""
    rel = f"{RECORDS.name}/photos/{name}"
    f = photo_file(rel)
    if f and f.parent == PHOTOS.resolve() and not any(rel in photo_list(t) for t in load_tasks()):
        f.unlink()


def load_settings():
    s = dict(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8-sig"))
            s = clean_settings({**s, **{k: v for k, v in saved.items() if k in DEFAULT_SETTINGS}})  # a leftover "priorities" key is ignored
        except (ValueError, AttributeError):  # a hand-edited file that is broken: run on the defaults instead of failing
            s = dict(DEFAULT_SETTINGS)
    return {**s, "priorities": PRIORITIES}


def clean_settings(s):
    """Validate and normalise a settings dict (it comes from the page or an uploaded file); returns only the known keys."""
    out = {k: s[k] for k in DEFAULT_SETTINGS if k in s}

    def need(ok, code):
        if not ok:
            raise ValueError(code)
    need(isinstance(out["language"], str) and out["language"] in [f.stem for f in (ROOT / "locales").glob("*.json")], "invalid_language")
    need(out["theme"] in ("auto", "light", "dark"), "invalid_theme")
    need(isinstance(out["currency"], str) and re.fullmatch(r"([A-Z]{3})?", out["currency"]), "invalid_currency")
    need(isinstance(out["default_due_time"], str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", out["default_due_time"]), "invalid_time")
    need(out["default_priority"] in PRIORITIES, "invalid_priority")
    for k in ("types", "socials"):
        v = out[k]
        need(isinstance(v, list) and len(v) <= 50 and all(isinstance(x, str) and len(x.strip()) <= 40 for x in v), "invalid_list")
        items = []
        for x in (x.strip() for x in v):
            if x and x.lower() not in [i.lower() for i in items]:  # drop blanks and case-insensitive duplicates
                items.append(x)
        out[k] = items
    v = out["shortcuts"]
    need(isinstance(v, dict) and set(v) <= set(DEFAULT_SETTINGS["shortcuts"]), "invalid_shortcuts")
    v = out["shortcuts"] = {**DEFAULT_SETTINGS["shortcuts"], **v}  # a partial file keeps the other keys
    need(all(isinstance(x, str) and SHORTCUT_RE.fullmatch(x) for x in v.values()) and len(set(v.values())) == len(v), "invalid_shortcuts")
    v = out["title_order"]
    need(isinstance(v, list) and len(set(v)) == len(v) and "title" in v and all(x in TITLE_PARTS for x in v), "invalid_title_order")
    return out


def save_settings(s):
    out = clean_settings(s)
    tmp = SETTINGS_FILE.with_name(SETTINGS_FILE.name + ".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SETTINGS_FILE)  # atomic: a reader never sees a half-written file
    return out


def ensure_settings_file():
    if not SETTINGS_FILE.exists():
        save_settings(load_settings())


def import_settings(data):
    """Apply a (possibly partial) settings file. Nothing is applied if any value is invalid."""
    if not isinstance(data, dict):
        raise ValueError("invalid_settings_file")
    known = {k: v for k, v in data.items() if k in DEFAULT_SETTINGS}
    save_settings({**load_settings(), **known})
    return {"applied": list(known), "ignored": [k for k in data if k not in DEFAULT_SETTINGS]}


def load_tasks():
    tasks = []
    for name in ("active.csv", "completed.csv"):
        p = RECORDS / name
        if p.exists():
            with p.open(newline="", encoding="utf-8-sig") as f:
                tasks += [{k: row.get(k) or "" for k in FIELDS} for row in csv.DictReader(f)]
    return tasks


def save_tasks(tasks):
    # Limitation: one file per kind, no size rollover; add active_2.csv splitting if files grow huge
    RECORDS.mkdir(parents=True, exist_ok=True)
    for name, done in (("active.csv", False), ("completed.csv", True)):
        tmp = RECORDS / (name + ".tmp")
        with tmp.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(t for t in tasks if (t["status"] == "Completed") == done)
        tmp.replace(RECORDS / name)  # atomic: a crash never leaves a half-written csv


def clean_task(data, old=None):
    t = {k: "" for k in FIELDS}
    t.update(old or {})
    for k in FIELDS:
        if k in data:
            t[k] = data[k] if isinstance(data[k], str) else json.dumps(data[k], ensure_ascii=False) \
                if k == "client_socials" else str(data[k])
    if not t["title"].strip():
        raise ValueError("title_required")
    if t["status"] not in STATUSES:
        paid = t["paid"] == "1"
        t["status"] = "Ready" if paid or t["type"] != "Commission" else "Waitlist"
    t["estimate_min"] = parse_duration(data.get("estimate", format_duration(t["estimate_min"])))
    for k in ("price", "paid_amount"):
        if t[k].strip():
            try:
                ok = math.isfinite(float(t[k])) and float(t[k]) >= 0
            except ValueError:
                ok = False
            if not ok:
                raise ValueError("invalid_price")
    if "client_email" in data:  # only re-validate when changed, so a bad legacy value can't block other edits
        t["client_email"] = t["client_email"].strip()
        if t["client_email"] and not EMAIL_RE.fullmatch(t["client_email"]):
            raise ValueError("invalid_email")
    t["currency"] = t["currency"].strip().upper()
    if not re.fullmatch(r"([A-Z]{3})?", t["currency"]):
        raise ValueError("invalid_currency")
    t["paid"] = "1" if str(t["paid"]) in ("1", "true", "True") else ""
    if not t["id"]:
        t["id"], t["created"] = uuid.uuid4().hex[:8], datetime.now().isoformat(timespec="minutes")
    return t


def upsert(data):
    tasks = load_tasks()
    old = next((t for t in tasks if t["id"] == data.get("id")), None)
    new = clean_task(data, old)
    if "snoozed_until" in data:
        if new["snoozed_until"] and not new["snoozed_from"]:  # snoozing parks the task in Waitlist; re-snoozing keeps the first status
            new["snoozed_from"], new["status"] = new["status"], "Waitlist"
        elif not new["snoozed_until"] and new["snoozed_from"]:  # cancelled: back where it was
            new["status"], new["snoozed_from"] = new["snoozed_from"], ""
    elif "status" in data and new["snoozed_from"]:  # moved by hand while snoozed: that ends the snooze
        new["snoozed_until"] = new["snoozed_from"] = ""
    for rel in set(photo_list(old)) - set(photo_list(new)):  # photos removed from the task
        discard_photo(rel)
    organize_photos(new)
    tasks = [t for t in tasks if t["id"] != new["id"]] + [new]
    save_tasks(tasks)
    return new


def delete_task(tid):
    tasks = load_tasks()
    gone = next((t for t in tasks if t["id"] == tid), None)
    for rel in photo_list(gone):  # finished or not, a deleted task takes its photos with it
        discard_photo(rel)
    save_tasks([t for t in tasks if t["id"] != tid])


def wake_snoozed():
    """Tasks whose snooze has ended go back to the status they had before it."""
    tasks, now = load_tasks(), datetime.now().isoformat(timespec="minutes")  # snoozed_until is local time, like now()
    woke = [t for t in tasks if t["snoozed_from"] and t["snoozed_until"] <= now]
    for t in woke:
        t["status"], t["snoozed_from"], t["snoozed_until"] = t["snoozed_from"], "", ""
        organize_photos(t)  # it may be returning to Completed
    if woke:
        save_tasks(tasks)


def view(t):
    return {**t, "estimate": format_duration(t["estimate_min"])}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json", headers=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        if ctype.startswith("text/") or ctype == "application/json":
            ctype += "; charset=utf-8"
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        return self.rfile.read(int(self.headers.get("Content-Length", 0)))

    def _file(self, path, ctype=None):
        if path.is_file():
            self._send(200, path.read_bytes(), ctype or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        else:
            self._send(404, {"error": "not found"})

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/":
            self._file(ROOT / "static" / "index.html", "text/html")
        elif p == "/api/state":
            with DATA_LOCK:  # build under the lock, send outside it so a slow browser can't stall saves
                wake_snoozed()
                state = {"tasks": [view(t) for t in load_tasks()], "settings": load_settings(),
                         "statuses": STATUSES, "version": VERSION, "settings_file": str(SETTINGS_FILE.resolve()),
                         "finished_photos": {"count": len(finished_photos()),
                                             "bytes": sum(f.stat().st_size for f in finished_photos())}, "author": AUTHOR, "year": YEAR,
                         "languages": {f.stem: json.loads(f.read_text(encoding="utf-8"))["name"]
                                       for f in sorted((ROOT / "locales").glob("*.json"))}}
            self._send(200, state)
        elif p == "/api/settings/file":
            with DATA_LOCK:
                ensure_settings_file()
                data = SETTINGS_FILE.read_bytes()
            self._send(200, data, "application/json",
                       {"Content-Disposition": 'attachment; filename="pupqueue-settings.json"'})
        elif m := re.fullmatch(r"/locales/([a-z\-]+)\.json", p):
            self._file(ROOT / "locales" / f"{m[1]}.json", "application/json")
        elif p.startswith("/photos/"):
            f = photo_file("photos/" + unquote(p[8:]))  # resolves inside photos/ only: blocks path traversal
            self._file(f) if f else self._send(404, {"error": "not found"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        with DATA_LOCK:
            self._post()

    def do_DELETE(self):
        with DATA_LOCK:
            self._delete()

    def _post(self):
        try:
            if self.path == "/api/tasks":
                self._send(200, view(upsert(json.loads(self._body()))))
            elif self.path == "/api/settings":
                body = json.loads(self._body())
                if not isinstance(body, dict):
                    raise ValueError("invalid_settings_file")
                save_settings({**load_settings(), **body})
                self._send(200, load_settings())
            elif self.path == "/api/settings/import":
                raw = self._body()
                if len(raw) > 100_000:
                    raise ValueError("file_too_big")
                try:
                    data = json.loads(raw.decode("utf-8-sig"))
                except ValueError:
                    raise ValueError("invalid_settings_file")
                self._send(200, {**import_settings(data), "settings": load_settings()})
            elif self.path == "/api/photos/clear-finished":
                self._send(200, clear_finished_photos())
            elif self.path == "/api/upload":
                # the browser sends the name percent-encoded: HTTP headers can't carry raw non-ASCII (e.g. Chinese) names
                ext = Path(unquote(self.headers.get("X-Filename", ""))).suffix.lstrip(".").lower()
                if ext not in IMAGE_EXTS:
                    raise ValueError("unsupported_image")
                PHOTOS.mkdir(parents=True, exist_ok=True)
                name = f"{uuid.uuid4().hex[:10]}.{ext}"
                (PHOTOS / name).write_bytes(self._body())
                self._send(200, {"path": f"{RECORDS.name}/photos/{name}"})
            else:
                self._send(404, {"error": "not found"})
        except (ValueError, KeyError) as e:
            self._send(400, {"error": str(e)})

    def _delete(self):
        if m := re.fullmatch(r"/api/tasks/(\w+)", self.path):
            delete_task(m[1])
            self._send(200, {"ok": True})
        elif m := re.fullmatch(r"/api/photos/([^/]+)", self.path):
            delete_unsaved_photo(unquote(m[1]))
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    migrate()
    ensure_settings_file()
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)  # localhost only: no auth
    print(f"PupQueue v{VERSION} running at http://127.0.0.1:{port}  (Ctrl+C to stop)")
    webbrowser.open(f"http://127.0.0.1:{port}")
    srv.serve_forever()
