import csv, http.client, json, re, tempfile, threading, urllib.parse, urllib.request, uuid
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
    assert p.startswith("task_records/photos/") and (pq.RECORDS.parent / p).read_bytes() == b"img"
    assert call("POST", "/api/upload", b"x", {"X-Filename": "evil.html"})["error"] == "unsupported_image"
    with urllib.request.urlopen(base + "/" + p.removeprefix("task_records/")) as r:
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

def test_settings_file_and_import():
    tmp = Path(tempfile.mkdtemp())
    pq.SETTINGS_FILE = tmp / "settings.json"
    srv = pq.ThreadingHTTPServer(("127.0.0.1", 0), pq.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    def call(m, u, b=None):
        data = b if isinstance(b, bytes) else json.dumps(b).encode() if b is not None else None
        try: return json.load(urllib.request.urlopen(urllib.request.Request(base + u, data, method=m)))
        except urllib.error.HTTPError as e: return {"status": e.code, **json.load(e)}
    saved = lambda: json.loads(pq.SETTINGS_FILE.read_text("utf-8"))
    # the file exists (created on demand) and is what the download serves
    assert not pq.SETTINGS_FILE.exists()
    r = urllib.request.urlopen(base + "/api/settings/file")
    assert pq.SETTINGS_FILE.exists() and r.read() == pq.SETTINGS_FILE.read_bytes() and "attachment" in r.headers["Content-Disposition"]
    state = call("GET", "/api/state")
    assert state["settings_file"] == str(pq.SETTINGS_FILE.resolve()) and state["settings"]["priorities"] == pq.PRIORITIES
    # priorities are fixed: never stored, never editable, a stale key in the file is ignored
    assert "priorities" not in saved()
    call("POST", "/api/settings", {"priorities": ["x"], "theme": "dark"})
    assert "priorities" not in saved() and call("GET", "/api/state")["settings"]["priorities"] == pq.PRIORITIES
    pq.SETTINGS_FILE.write_text(json.dumps({**saved(), "priorities": ["old"]}), "utf-8")
    assert pq.load_settings()["priorities"] == pq.PRIORITIES and call("GET", "/api/state")["settings"]["theme"] == "dark"
    # lists are trimmed, de-duplicated (ignoring case) and stripped of blanks
    s = call("POST", "/api/settings", {"types": [" Gift ", "gift", "", "Commission"], "socials": ["QQ"]})
    assert s["types"] == ["Gift", "Commission"] and saved()["types"] == ["Gift", "Commission"]
    # each setting is validated
    for bad, code in [({"types": "Gift"}, "invalid_list"), ({"types": ["x" * 41]}, "invalid_list"), ({"socials": [1]}, "invalid_list"),
                      ({"title_order": ["type", "price"]}, "invalid_title_order"), ({"title_order": ["title", "title"]}, "invalid_title_order"),
                      ({"title_order": ["title", "bogus"]}, "invalid_title_order"), ({"default_priority": "Urgent"}, "invalid_priority"),
                      ({"language": "xx"}, "invalid_language"), ({"theme": "neon"}, "invalid_theme"), ({"currency": "euro"}, "invalid_currency"),
                      ({"default_due_time": "9:00"}, "invalid_time"), ({"shortcuts": "Enter"}, "invalid_shortcuts"),
                      ({"shortcuts": {"bogus": "A"}}, "invalid_shortcuts"), ({"shortcuts": {"save_task": "Ctrl+ Enter"}}, "invalid_shortcuts"),
                      ({"shortcuts": {"save_task": "Enter"}}, "invalid_shortcuts")]:  # same keys as finish_field
        assert call("POST", "/api/settings", bad)["error"] == code, bad
    # a partial shortcuts value keeps the other shortcut
    assert call("POST", "/api/settings", {"shortcuts": {"save_task": "Ctrl+S"}})["shortcuts"] == {"save_task": "Ctrl+S", "finish_field": "Enter"}
    assert call("POST", "/api/settings", {"title_order": ["paid", "title", "type"], "default_priority": "Low"})["title_order"] == ["paid", "title", "type"]
    # importing a preset file: partial files are merged, unknown keys are reported and ignored
    before = saved()
    r = call("POST", "/api/settings/import", json.dumps({"theme": "light", "types": ["A", "B"], "priorities": ["x"], "extra": 1}).encode())
    assert r["applied"] == ["theme", "types"] and r["ignored"] == ["priorities", "extra"]
    assert saved()["theme"] == "light" and saved()["types"] == ["A", "B"] and saved()["socials"] == before["socials"]
    # a bad value, a non-object or junk applies nothing
    before = saved()
    assert call("POST", "/api/settings/import", json.dumps({"theme": "light", "currency": "euro"}).encode())["error"] == "invalid_currency"
    for junk in (b"[1,2]", b"not json", b"\xff\xfe\x00", b'"text"'):
        assert call("POST", "/api/settings/import", junk)["error"] == "invalid_settings_file", junk
    assert call("POST", "/api/settings/import", b"{" + b" " * 100_001 + b"}")["error"] == "file_too_big"
    assert saved() == before
    assert call("POST", "/api/settings/import", b"\xef\xbb\xbf" + json.dumps({"theme": "auto"}).encode())["applied"] == ["theme"]  # Windows editors add a BOM

def test_concurrent_writes_do_not_lose_updates():
    tmp = Path(tempfile.mkdtemp())
    pq.SETTINGS_FILE = tmp / "settings.json"
    pq.RECORDS, pq.PHOTOS = tmp / "task_records", tmp / "task_records" / "photos"
    srv = pq.ThreadingHTTPServer(("127.0.0.1", 0), pq.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    def post(u, body):
        urllib.request.urlopen(urllib.request.Request(base + u, json.dumps(body).encode(), method="POST")).read()
    patches = [{"currency": "EUR"}, {"default_due_time": "09:00"}, {"theme": "dark"}, {"default_priority": "High"}, {"types": ["A"]}, {"socials": ["B"]}]
    jobs = [threading.Thread(target=post, args=("/api/settings", p)) for p in patches]
    jobs += [threading.Thread(target=post, args=("/api/tasks", {"title": f"t{i}"})) for i in range(12)]
    failures = []
    def read_state():  # the page reads while saves happen: it must never see a half-written file
        for _ in range(150):
            try: json.load(urllib.request.urlopen(base + "/api/state"))
            except Exception as e: failures.append(repr(e))
    def keep_saving():
        for i in range(60): post("/api/settings", {"types": [f"T{i}"]})
    extra = [threading.Thread(target=read_state) for _ in range(3)] + [threading.Thread(target=keep_saving)]
    for t in jobs + extra: t.start()
    for t in jobs + extra: t.join()
    assert not failures, failures[:3]
    post("/api/settings", {"types": ["A"]})  # keep_saving ran concurrently; settle on a known value
    s = pq.load_settings()
    assert (s["currency"], s["default_due_time"], s["theme"], s["default_priority"], s["types"], s["socials"]) == ("EUR", "09:00", "dark", "High", ["A"], ["B"])
    assert sorted(t["title"] for t in pq.load_tasks()) == sorted(f"t{i}" for i in range(12))

def test_broken_settings_file_falls_back_to_defaults():
    tmp = Path(tempfile.mkdtemp())
    pq.SETTINGS_FILE = tmp / "settings.json"
    for broken in ("{not json", "[1, 2]", '{"theme": "neon"}', '{"types": "Gift"}', ""):
        pq.SETTINGS_FILE.write_text(broken, "utf-8")
        assert pq.load_settings() == {**pq.DEFAULT_SETTINGS, "priorities": pq.PRIORITIES}, broken
    pq.SETTINGS_FILE.write_bytes(b"\xef\xbb\xbf" + json.dumps({"theme": "dark"}).encode())  # a Windows editor's BOM
    assert pq.load_settings()["theme"] == "dark"

def _sandbox():
    tmp = Path(tempfile.mkdtemp())
    pq.RECORDS, pq.PHOTOS, pq.SETTINGS_FILE = tmp / "task_records", tmp / "task_records" / "photos", tmp / "s.json"
    return tmp

def _upload(data):  # what /api/upload does: a random-named file at the top of photos/
    pq.PHOTOS.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex[:10]}.png"
    (pq.PHOTOS / name).write_bytes(data)
    return "task_records/photos/" + name

def _files(folder):
    return sorted(f.name for f in folder.iterdir() if f.is_file()) if folder.is_dir() else []

def _csv_photos(name, title):
    with (pq.RECORDS / name).open(newline="", encoding="utf-8-sig") as f:
        return next(r["photos"] for r in csv.DictReader(f) if r["title"] == title)

def test_photos():
    tmp = _sandbox()
    fin = pq.PHOTOS / pq.FINISHED_DIR
    title = "白梅 / Cat: fan?art;"
    stem = pq.photo_stem(title)
    assert not set('\\/:*?"<>|;%#') & set(stem) and stem
    # named after the title; several photos get _2, _3 ...
    a = pq.upsert({"title": title, "type": "Gift", "photos": ";".join([_upload(b"1"), _upload(b"2")])})
    assert _files(pq.PHOTOS) == sorted([f"{stem}.png", f"{stem}_2.png"])
    assert (pq.PHOTOS / f"{stem}.png").read_bytes() == b"1"
    # the CSV row holds each photo's address (from the project folder), and the file is really there
    addr = _csv_photos("active.csv", title)
    assert addr == f"task_records/photos/{stem}.png;task_records/photos/{stem}_2.png" == a["photos"]
    assert all((tmp / p).is_file() for p in addr.split(";"))
    assert pq.upsert({"title": "No pics"})["photos"] == "" and _csv_photos("active.csv", "No pics") == ""
    # changing the title renames the files
    a = pq.upsert({"id": a["id"], "title": "Dog", "photos": a["photos"]})
    assert _files(pq.PHOTOS) == ["Dog.png", "Dog_2.png"]
    # removing a photo of an unfinished task deletes the file
    a = pq.upsert({"id": a["id"], "photos": a["photos"].split(";")[0]})
    assert _files(pq.PHOTOS) == ["Dog.png"]
    a = pq.upsert({"id": a["id"], "photos": a["photos"] + ";" + _upload(b"3")})
    assert _files(pq.PHOTOS) == ["Dog.png", "Dog_2.png"]
    # finishing moves them to photos/finished_task_photos; un-finishing moves them back
    a = pq.upsert({"id": a["id"], "status": "Completed"})
    assert _files(pq.PHOTOS) == [] and _files(fin) == ["Dog.png", "Dog_2.png"]
    assert a["photos"] == f"task_records/photos/{pq.FINISHED_DIR}/Dog.png;task_records/photos/{pq.FINISHED_DIR}/Dog_2.png"
    assert _csv_photos("completed.csv", "Dog") == a["photos"]  # a finished task stays in the local csv with its photo addresses
    a = pq.upsert({"id": a["id"], "status": "WIP"})
    assert _files(fin) == [] and _files(pq.PHOTOS) == ["Dog.png", "Dog_2.png"]
    # finished tasks keep their photos while they exist; removing one photo from a finished task deletes that file
    a = pq.upsert({"id": a["id"], "status": "Completed"})
    a = pq.upsert({"id": a["id"], "photos": a["photos"].split(";")[0]})
    assert _files(fin) == ["Dog.png"] and a["photos"].count(";") == 0
    # deleting a task deletes its photos, finished or not
    pq.delete_task(a["id"])
    assert _files(fin) == [] and [t["title"] for t in pq.load_tasks()] == ["No pics"]
    b = pq.upsert({"title": "Bee", "photos": _upload(b"b")})
    pq.delete_task(b["id"])
    assert _files(pq.PHOTOS) == []
    # same title on two tasks never clobbers a file
    c1 = pq.upsert({"title": "Same", "photos": _upload(b"c1")})
    c2 = pq.upsert({"title": "Same", "photos": _upload(b"c2")})
    assert c1["photos"] != c2["photos"] and {(tmp / p).read_bytes() for p in (c1["photos"], c2["photos"])} == {b"c1", b"c2"}
    # an upload nobody saved can be dropped; a saved one cannot
    loose = _upload(b"loose")
    pq.delete_unsaved_photo(loose.split("/")[-1]); pq.delete_unsaved_photo(c1["photos"].split("/")[-1])
    assert not (tmp / loose).exists() and (tmp / c1["photos"]).exists()
    # clear-all deletes the finished tasks' photos and leaves no dangling addresses
    d = pq.upsert({"title": "Done", "status": "Completed", "photos": _upload(b"d")})
    assert len(pq.finished_photos()) == 1
    r = pq.clear_finished_photos()
    assert r["deleted"] == 1 and r["bytes"] > 0 and pq.finished_photos() == []
    assert next(t for t in pq.load_tasks() if t["id"] == d["id"])["photos"] == ""
    assert (tmp / c1["photos"]).exists()  # unfinished tasks are untouched

def test_photo_urls():
    tmp = _sandbox()
    srv = pq.ThreadingHTTPServer(("127.0.0.1", 0), pq.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    t = pq.upsert({"title": "白梅 头像", "photos": _upload(b"png!")})
    def get(path):
        c = http.client.HTTPConnection("127.0.0.1", srv.server_port); c.request("GET", path); r = c.getresponse(); return r.status, r.read()
    url = lambda addr: "/" + urllib.parse.quote(addr.removeprefix("task_records/"))  # what the page does with a CSV address
    assert get(url(t["photos"])) == (200, b"png!")  # non-ASCII + space in the file name
    (tmp / "secret.txt").write_text("s")
    for bad in ("/photos/../../secret.txt", "/photos/%2e%2e/%2e%2e/secret.txt", "/photos/..%2f..%2fsecret.txt", "/photos/nope.png"):
        assert get(bad)[0] == 404, bad
    pq.upsert({"id": t["id"], "status": "Completed"})
    state = json.load(urllib.request.urlopen(f"http://127.0.0.1:{srv.server_port}/api/state"))
    assert state["finished_photos"]["count"] == 1 and state["tasks"][0]["photos"].startswith(f"task_records/photos/{pq.FINISHED_DIR}/")
    assert get(url(state["tasks"][0]["photos"]))[0] == 200

def test_legacy_rows_and_migration():
    tmp = Path(tempfile.mkdtemp())
    root, pq.ROOT = pq.ROOT, tmp
    pq.RECORDS, pq.PHOTOS = tmp / "task_records", tmp / "task_records" / "photos"
    (tmp / "task records").mkdir()
    # V1 files: no currency column; photos kept as 'photos/<random>.png' (partial address, random name)
    (tmp / "task records" / "active.csv").write_text("id,title,status,photos\nab12,Old,Ready,photos/x.png\n", "utf-8-sig")
    (tmp / "task records" / "completed.csv").write_text("id,title,status,photos\nzz99,Done one,Completed,photos/y.png\n", "utf-8-sig")
    (tmp / "photos").mkdir()
    (tmp / "photos" / "x.png").write_bytes(b"1")
    (tmp / "photos" / "y.png").write_bytes(b"2")
    try: pq.migrate()
    finally: pq.ROOT = root
    assert not (tmp / "task records").exists() and not (tmp / "photos").exists()
    # photos are renamed after their task, finished ones filed away, and the csv holds the full address
    assert (pq.PHOTOS / "Old.png").read_bytes() == b"1" and (pq.PHOTOS / pq.FINISHED_DIR / "Done one.png").read_bytes() == b"2"
    assert _csv_photos("active.csv", "Old") == "task_records/photos/Old.png"
    assert _csv_photos("completed.csv", "Done one") == f"task_records/photos/{pq.FINISHED_DIR}/Done one.png"
    old = next(t for t in pq.load_tasks() if t["title"] == "Old")
    assert old["currency"] == ""
    pq.upsert({"id": "ab12", "status": "WIP"})  # editing a legacy row must not fail
    assert next(t for t in pq.load_tasks() if t["id"] == "ab12")["status"] == "WIP"
