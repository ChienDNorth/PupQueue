"""PupQueue - commission queue tracker. Stdlib only. Run: python pupqueue.py [port]"""
import csv, json, math, mimetypes, re, shutil, sys, uuid, webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

VERSION, AUTHOR, YEAR = "1.1.0", "北原啸ChienDNorth", 2026
ROOT = Path(__file__).parent
RECORDS = ROOT / "task_records"
PHOTOS = RECORDS / "photos"
SETTINGS_FILE = ROOT / "settings.json"
FIELDS = ["id", "title", "type", "priority", "price", "currency", "paid", "paid_amount", "paid_time",
          "estimate_min", "due", "client_name", "client_email", "client_socials",
          "notes", "photos", "status", "snoozed_until", "created"]
STATUSES = ["Waitlist", "Ready", "WIP", "Completed"]
DEFAULT_SETTINGS = {
    "language": "en",
    "types": ["Gift", "Self Project", "Drawing Swap", "Commission", "Else"],
    "priorities": ["Critical", "High", "Medium", "Low", "Lowest"],  # highest first; bars shown = list length
    "default_priority": "Medium",
    "socials": ["QQ", "Twitter", "Vgen", "Mihuashi"],
    "currency": "",  # "" = follow the language (en -> USD, zh -> CNY, see locales/*.json)
    "theme": "auto",  # auto = follow the system, or light / dark
    "default_due_time": "00:00",  # time of day filled in when a due date is picked
    "title_order": ["type", "social", "title", "price", "paid"],  # parts of the displayed title
}
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
    """Move data from the V1 layout ('task records/', photos/) into task_records/."""
    old = ROOT / "task records"
    if old.is_dir() and not RECORDS.exists():
        old.rename(RECORDS)
    old_photos = ROOT / "photos"
    if old_photos.is_dir():
        PHOTOS.mkdir(parents=True, exist_ok=True)
        for f in old_photos.iterdir():
            shutil.move(str(f), PHOTOS / f.name)
        old_photos.rmdir()


def load_settings():
    s = dict(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        s.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    return s


def save_settings(s):
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", s["default_due_time"]):
        raise ValueError("invalid_time")
    if not re.fullmatch(r"([A-Z]{3})?", s["currency"]):
        raise ValueError("invalid_currency")
    if s["theme"] not in ("auto", "light", "dark"):
        raise ValueError("invalid_theme")
    SETTINGS_FILE.write_text(json.dumps({k: s[k] for k in DEFAULT_SETTINGS if k in s},
                                        ensure_ascii=False, indent=2), encoding="utf-8")


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
    tasks = [t for t in tasks if t["id"] != new["id"]] + [new]
    save_tasks(tasks)
    return new


def view(t):
    return {**t, "estimate": format_duration(t["estimate_min"])}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        if ctype.startswith("text/") or ctype == "application/json":
            ctype += "; charset=utf-8"
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
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
            self._send(200, {"tasks": [view(t) for t in load_tasks()], "settings": load_settings(),
                             "statuses": STATUSES, "version": VERSION, "author": AUTHOR, "year": YEAR,
                             "languages": {f.stem: json.loads(f.read_text(encoding="utf-8"))["name"]
                                           for f in sorted((ROOT / "locales").glob("*.json"))}})
        elif m := re.fullmatch(r"/locales/([a-z\-]+)\.json", p):
            self._file(ROOT / "locales" / f"{m[1]}.json", "application/json")
        elif m := re.fullmatch(r"/photos/([\w.\-]+)", p):  # regex blocks path traversal
            self._file(PHOTOS / m[1])
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            if self.path == "/api/tasks":
                self._send(200, view(upsert(json.loads(self._body()))))
            elif self.path == "/api/settings":
                s = {**load_settings(), **json.loads(self._body())}
                save_settings(s)
                self._send(200, s)
            elif self.path == "/api/upload":
                # the browser sends the name percent-encoded: HTTP headers can't carry raw non-ASCII (e.g. Chinese) names
                ext = Path(unquote(self.headers.get("X-Filename", ""))).suffix.lstrip(".").lower()
                if ext not in IMAGE_EXTS:
                    raise ValueError("unsupported_image")
                PHOTOS.mkdir(parents=True, exist_ok=True)
                name = f"{uuid.uuid4().hex[:10]}.{ext}"
                (PHOTOS / name).write_bytes(self._body())
                self._send(200, {"path": f"photos/{name}"})
            else:
                self._send(404, {"error": "not found"})
        except (ValueError, KeyError) as e:
            self._send(400, {"error": str(e)})

    def do_DELETE(self):
        if m := re.fullmatch(r"/api/tasks/(\w+)", self.path):
            save_tasks([t for t in load_tasks() if t["id"] != m[1]])
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    migrate()
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)  # localhost only: no auth
    print(f"PupQueue v{VERSION} running at http://127.0.0.1:{port}  (Ctrl+C to stop)")
    webbrowser.open(f"http://127.0.0.1:{port}")
    srv.serve_forever()
