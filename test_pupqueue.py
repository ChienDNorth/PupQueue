import json, re, tempfile, threading, urllib.request
from pathlib import Path
import pupqueue as pq

CANON = re.compile(r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)min)?")

def test_duration():
    # every minute count: formatted form is canonical (h < 24, min < 60, no zero parts) and parses back
    for m in range(30000):
        s = pq.format_duration(m)
        d, h, n = (int(x or 0) for x in CANON.fullmatch(s).groups()) if m else (0, 0, 0)
        assert h < 24 and n < 60 and d * 1440 + h * 60 + n == m, (m, s)
        assert pq.parse_duration(s) == pq.parse_duration(str(m)) == pq.parse_duration(f"{m}min") == m, (m, s)
    # any mix of units gives the same total, and in any spelling
    for d in range(4):
        for h in range(0, 49, 5):
            for n in range(0, 200, 13):
                total = d * 1440 + h * 60 + n
                for spelling in (f"{d}d{h}h{n}min", f"{d} days {h} hours {n} minutes", f"{d}天{h}小时{n}分钟"):
                    assert pq.parse_duration(spelling) == total, spelling
                assert pq.format_duration(pq.parse_duration(f"{d}d{h}h{n}")) == pq.format_duration(total)  # last unit omitted = min
    for h in range(300):  # whole hours and days convert up
        assert pq.parse_duration(f"{h}h") == h * 60 and pq.parse_duration(f"{h}d") == h * 1440
    assert pq.parse_duration("1.5h") == 90 and pq.parse_duration("0.25d") == 360 and pq.parse_duration("") == ""
    for bad in ("abc", "5x", "h", "-5", "1.5.5", "1 h 2 x", "min5"):
        try: pq.parse_duration(bad); assert False, bad
        except ValueError: pass

def test_email():
    for ok in ("a@b.co", "first.last+tag@mail.example.com", "x_y@sub-domain.org"):
        assert pq.EMAIL_RE.fullmatch(ok), ok
    for bad in ("abc", "a@b", "a@@b.com", "a b@c.com", "@b.com", "a@b.", "a..b@c.com", ".a@c.com", "a@-b.com"):
        assert not pq.EMAIL_RE.fullmatch(bad), bad

def test_storage_and_api():
    tmp = Path(tempfile.mkdtemp())
    pq.RECORDS, pq.PHOTOS, pq.SETTINGS_FILE = tmp / "task_records", tmp / "task_records" / "photos", tmp / "s.json"
    srv = pq.ThreadingHTTPServer(("127.0.0.1", 0), pq.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    def call(m, u, b=None, h={}):
        data = b if isinstance(b, bytes) else json.dumps(b).encode() if b is not None else None
        try: return json.load(urllib.request.urlopen(urllib.request.Request(base + u, data, h, method=m)))
        except urllib.error.HTTPError as e: return {"status": e.code, **json.load(e)}
    a = call("POST", "/api/tasks", {"title": "Cmsn", "type": "Commission", "estimate": "70min", "price": "50", "currency": "cny"})
    b = call("POST", "/api/tasks", {"title": "Gift", "type": "Gift", "client_socials": [{"net": "QQ", "handle": "1"}]})
    assert a["status"] == "Waitlist" and b["status"] == "Ready" and a["estimate"] == "1h10min" and a["currency"] == "CNY"
    call("POST", "/api/tasks", {"id": a["id"], "status": "Completed"})
    assert "Cmsn" in (pq.RECORDS / "completed.csv").read_text("utf-8-sig")
    assert "Cmsn" not in (pq.RECORDS / "active.csv").read_text("utf-8-sig")
    assert call("POST", "/api/tasks", {"title": ""})["error"] == "title_required"
    assert call("POST", "/api/tasks", {"title": "x", "price": "abc"})["status"] == 400
    assert call("POST", "/api/tasks", {"title": "x", "price": "-1"})["status"] == 400
    assert call("POST", "/api/tasks", {"title": "x", "estimate": "5x"})["error"] == "invalid_estimate"
    assert call("POST", "/api/tasks", {"title": "x", "client_email": "nope@x"})["error"] == "invalid_email"
    ok = call("POST", "/api/tasks", {"id": b["id"], "client_email": " me@example.com "})
    assert ok["client_email"] == "me@example.com"
    # photos land in task_records/photos, even for a Chinese filename (sent percent-encoded)
    p = call("POST", "/api/upload", b"img", {"X-Filename": "%E5%9B%BE%E7%89%87.PNG"})["path"]
    assert (pq.RECORDS / p).read_bytes() == b"img"
    assert call("POST", "/api/upload", b"x", {"X-Filename": "evil.html"})["error"] == "unsupported_image"
    with urllib.request.urlopen(base + "/" + p) as r:
        assert r.read() == b"img" and r.headers["Content-Type"] == "image/png"
    state = call("GET", "/api/state")
    assert len(state["tasks"]) == 2 and "en" in state["languages"] and state["version"] == pq.VERSION
    assert state["settings"]["default_due_time"] == "00:00" and state["settings"]["currency"] == ""
    assert call("POST", "/api/settings", {"default_due_time": "25:00"})["error"] == "invalid_time"
    assert call("POST", "/api/settings", {"currency": "euro"})["error"] == "invalid_currency"
    assert state["settings"]["theme"] == "auto" and call("POST", "/api/settings", {"theme": "neon"})["error"] == "invalid_theme"
    assert call("POST", "/api/settings", {"theme": "dark"})["theme"] == "dark"
    assert call("POST", "/api/settings", {"currency": "EUR", "default_due_time": "18:00"})["currency"] == "EUR"
    call("DELETE", f"/api/tasks/{b['id']}")
    assert len(call("GET", "/api/state")["tasks"]) == 1

def test_legacy_rows_and_migration():
    tmp = Path(tempfile.mkdtemp())
    root, pq.ROOT = pq.ROOT, tmp
    pq.RECORDS, pq.PHOTOS = tmp / "task_records", tmp / "task_records" / "photos"
    (tmp / "task records").mkdir()
    (tmp / "task records" / "active.csv").write_text("id,title,status\nab12,Old,Ready\n", "utf-8-sig")  # V1 file: no currency column
    (tmp / "photos").mkdir()
    (tmp / "photos" / "x.png").write_bytes(b"1")
    try: pq.migrate()
    finally: pq.ROOT = root
    assert not (tmp / "task records").exists() and not (tmp / "photos").exists()
    assert (pq.PHOTOS / "x.png").read_bytes() == b"1"
    [t] = pq.load_tasks()
    assert t["title"] == "Old" and t["currency"] == ""
    pq.upsert({"id": "ab12", "status": "WIP"})  # editing a legacy row must not fail
    assert pq.load_tasks()[0]["status"] == "WIP"
