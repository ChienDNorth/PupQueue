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
    assert [pq.parse_duration(x) for x in ("0.4", "0.5", "1.5", "2.5")] == [0, 1, 2, 3]  # halves round up, every time
    for s, m in (("1min30", 1), ("1min20", 1), ("1m30", 1), ("1分30", 1), ("2h1min30", 121), ("1h30", 90), ("1d2", 1442)):
        assert pq.parse_duration(s) == m, s  # a number after minutes would be seconds: left out
    for bad in ("abc", "5x", "h", "-5", "1.5.5", "1 h 2 x", "min5", "9" * 400):
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
    a = call("POST", "/api/tasks", {"title": "Cmsn", "type": "Commission", "priority": "Low", "estimate": "70min", "price": "50", "currency": "cny"})
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
    ok = call("POST", "/api/tasks", {"id": b["id"], "client_email": None, "notes": None, "estimate": None})  # JSON null clears, never stores "None"
    assert ok["client_email"] == ok["notes"] == ok["estimate"] == "" and ok["title"] == "Gift"
    c = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=5)  # a negative length must not hang the server
    c.putrequest("POST", "/api/tasks"); c.putheader("Content-Length", "-1"); c.endheaders()
    assert c.getresponse().status == 400
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
    assert call("POST", "/api/settings/import", b"{" + b" " * pq.SETTINGS_FILE_MAX + b"}")["error"] == "file_too_big"
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

def test_snooze_parks_in_waitlist_and_returns():
    _sandbox()
    later, past = "2999-01-01T00:00", "2000-01-01T00:00"
    t = pq.upsert({"title": "S", "status": "WIP"})
    t = pq.upsert({"id": t["id"], "snoozed_until": later})
    assert (t["status"], t["snoozed_from"]) == ("Waitlist", "WIP")
    t = pq.upsert({"id": t["id"], "snoozed_until": "2999-02-01T00:00"})  # extending keeps the original status
    assert (t["status"], t["snoozed_from"]) == ("Waitlist", "WIP")
    t = pq.upsert({"id": t["id"], "snoozed_until": ""})  # cancel: back where it was
    assert (t["status"], t["snoozed_from"]) == ("WIP", "")
    pq.upsert({"id": t["id"], "status": "Ready"}); pq.upsert({"id": t["id"], "snoozed_until": later})
    pq.wake_snoozed()  # not over yet: stays parked
    assert pq.load_tasks()[0]["status"] == "Waitlist"
    rows = pq.load_tasks(); rows[0]["snoozed_until"] = past; pq.save_tasks(rows)
    pq.wake_snoozed()
    assert [(x["status"], x["snoozed_from"], x["snoozed_until"]) for x in pq.load_tasks()] == [("Ready", "", "")]
    pq.upsert({"id": t["id"], "snoozed_until": later})
    t = pq.upsert({"id": t["id"], "status": "Completed"})  # moved by hand while snoozed: snooze ends, no return later
    assert (t["status"], t["snoozed_from"], t["snoozed_until"]) == ("Completed", "", "")

def test_start_status_payment_and_completed_time():
    _sandbox()
    # new tasks: priority decides Waitlist or Ready (default priority Medium is ready); a status chosen by hand wins
    assert [pq.upsert({"title": p, "priority": p})["status"] for p in pq.PRIORITIES] == ["Ready"] * 3 + ["Waitlist"] * 2
    assert pq.upsert({"title": "no priority"})["status"] == "Ready"
    assert pq.upsert({"title": "by hand", "priority": "Critical", "status": "Waitlist"})["status"] == "Waitlist"
    pq.save_settings({**pq.load_settings(), "ready_priorities": ["Lowest", "Critical"]})
    assert pq.load_settings()["ready_priorities"] == ["Critical", "Lowest"]  # kept in priority order
    assert pq.upsert({"title": "m", "priority": "Medium"})["status"] == "Waitlist"
    # paid_ready: off by default; when on, paid tasks skip the waitlist unless Waitlist is chosen by hand or the task is snoozed
    assert pq.upsert({"title": "p0", "priority": "Low", "paid": True})["status"] == "Waitlist"
    pq.save_settings({**pq.load_settings(), "paid_ready": True})
    assert pq.upsert({"title": "p1", "priority": "Low", "paid": True})["status"] == "Ready"
    assert pq.upsert({"title": "p2", "priority": "Low", "paid": True, "status": "Waitlist"})["status"] == "Waitlist"
    w = pq.upsert({"title": "p3", "priority": "Low"})
    assert w["status"] == "Waitlist" and pq.upsert({"id": w["id"], "paid": True})["status"] == "Ready"
    z = pq.upsert({"title": "p4", "priority": "Low", "status": "WIP"}); z = pq.upsert({"id": z["id"], "snoozed_until": "2999-01-01T00:00"})
    assert pq.upsert({"id": z["id"], "paid": True})["status"] == "Waitlist"  # snoozed: stays parked
    try: pq.save_settings({**pq.load_settings(), "paid_ready": "yes"}); assert False
    except ValueError as e: assert str(e) == "invalid_paid_ready"
    assert pq.load_settings()["animations"] is True  # on by default
    try: pq.save_settings({**pq.load_settings(), "animations": "off"}); assert False
    except ValueError as e: assert str(e) == "invalid_animations"
    # payment method is kept only while paid
    t = pq.upsert({"title": "pay", "paid": True, "payment_method": " Paypal "})
    assert t["payment_method"] == "Paypal"
    assert pq.upsert({"id": t["id"], "paid": False})["payment_method"] == ""
    # completed_at: stamped when the task is finished, kept on later edits, cleared when it leaves Completed
    t = pq.upsert({"id": t["id"], "status": "Completed"})
    stamp = t["completed_at"]
    assert stamp and pq.upsert({"id": t["id"], "notes": "x"})["completed_at"] == stamp
    assert pq.upsert({"id": t["id"], "status": "WIP"})["completed_at"] == ""
    # a finished row from before completed_at existed reads its created date as the finish date
    old = pq.upsert({"id": t["id"], "status": "Completed"})
    tasks = pq.load_tasks(); next(x for x in tasks if x["id"] == old["id"])["completed_at"] = ""; pq.save_tasks(tasks)
    assert next(x for x in pq.load_tasks() if x["id"] == old["id"])["completed_at"] == old["created"]
    pq.upsert({"id": t["id"], "status": "WIP"})
    # settings: limits, priorities and icons are validated; an icon of a removed method is dropped
    for bad, code in [({"completed_limit": 0}, "invalid_completed_limit"), ({"completed_limit": "10"}, "invalid_completed_limit"),
                      ({"completed_limit": True}, "invalid_completed_limit"), ({"ready_priorities": ["Urgent"]}, "invalid_priority"),
                      ({"payment_icons": {"Paypal": "javascript:alert(1)"}}, "invalid_icon"), ({"payment_methods": [1]}, "invalid_list")]:
        try: pq.save_settings({**pq.load_settings(), **bad}); assert False, bad
        except ValueError as e: assert str(e) == code, (bad, e)
    icon = "data:image/png;base64,iVBORw0KGgo="
    s = pq.save_settings({**pq.load_settings(), "payment_icons": {"Paypal": icon, "Gone": icon}, "completed_limit": 25})
    assert s["payment_icons"] == {"Paypal": icon} and s["completed_limit"] == 25
    # a settings file with the largest icon on every one of the most methods still loads
    big = "data:image/png;base64," + "A" * (pq.ICON_MAX - 22)
    names = [f"M{i}" for i in range(pq.LIST_MAX)]
    data = json.dumps({**pq.load_settings(), "payment_methods": names, "payment_icons": dict.fromkeys(names, big)}).encode()
    assert len(data) <= pq.SETTINGS_FILE_MAX and len(pq.import_settings(json.loads(data))["applied"]) > 0

def test_projects_tasks_todos():
    _sandbox()
    assert pq.upsert({"title": "old"})["kind"] == "task"  # no kind given: a task, like rows from before v3.0
    p = pq.upsert({"title": "P", "kind": "project", "status": "Waitlist"})
    t = pq.upsert({"title": "T", "kind": "task", "parent": p["id"], "status": "Waitlist"})
    d = pq.upsert({"title": "D", "kind": "todo", "parent": t["id"], "status": "Waitlist"})
    for bad, code in [({"title": "x", "kind": "epic"}, "invalid_kind"), ({"title": "x", "kind": "todo", "parent": p["id"]}, "invalid_parent"),
                      ({"title": "x", "kind": "task", "parent": "nope"}, "invalid_parent"), ({"id": t["id"], "kind": "project"}, "invalid_kind")]:
        try: pq.upsert(bad); assert False, bad
        except ValueError as e: assert str(e) == code, (bad, e)
    status = lambda x: next(r["status"] for r in pq.load_tasks() if r["id"] == x["id"])
    # a todo moved to Ready pulls its task and the task's project along; WIP too
    pq.upsert({"id": d["id"], "status": "Ready"})
    assert (status(t), status(p)) == ("Ready", "Ready")
    pq.upsert({"id": d["id"], "status": "WIP"})
    assert (status(t), status(p)) == ("WIP", "WIP")
    # parents never move back, and finishing a child doesn't finish the parent
    pq.upsert({"id": d["id"], "status": "Ready"})
    pq.upsert({"id": d["id"], "status": "Completed"})
    assert (status(t), status(p)) == ("WIP", "WIP")
    # a snoozed parent that gets pulled along is no longer snoozed
    pq.upsert({"id": t["id"], "snoozed_until": "2999-01-01T00:00"})
    pq.upsert({"id": d["id"], "status": "WIP"})
    assert next((r["status"], r["snoozed_until"]) for r in pq.load_tasks() if r["id"] == t["id"]) == ("WIP", "")
    # deleting: "keep" detaches the direct children, "delete" removes everything inside
    pq.delete_task(p["id"], "keep")
    assert next(r["parent"] for r in pq.load_tasks() if r["id"] == t["id"]) == "" and status(d) == "WIP"
    pq.delete_task(t["id"], "delete")
    assert [r["title"] for r in pq.load_tasks()] == ["old"]
    try: pq.save_settings({**pq.load_settings(), "delete_children": "maybe"}); assert False
    except ValueError as e: assert str(e) == "invalid_delete_children"
    # type icon colours and the emoji setting are validated; an item's emoji is trimmed and kept
    s = pq.save_settings({**pq.load_settings(), "kind_colors": {"task": "#ABCDEF"}, "emoji": True})
    assert s["kind_colors"] == {**pq.DEFAULT_SETTINGS["kind_colors"], "task": "#abcdef"} and s["emoji"] is True
    assert pq.DEFAULT_SETTINGS["project_order"] == "due"  # Projects page keeps its old order (priority, then due date) until changed
    for bad, code in [({"kind_colors": {"task": "red"}}, "invalid_color"), ({"kind_colors": {"epic": "#000000"}}, "invalid_color"), ({"emoji": "yes"}, "invalid_bool"), ({"project_order": "random"}, "invalid_project_order")]:
        try: pq.save_settings({**pq.load_settings(), **bad}); assert False, bad
        except ValueError as e: assert str(e) == code, (bad, e)
    e = pq.upsert({"title": "E", "emoji": " 🐶 "})
    assert next(r["emoji"] for r in pq.load_tasks() if r["id"] == e["id"]) == "🐶"
    # a crossed-out todo is finished; reopening it clears the cross
    x = pq.upsert({"title": "X", "kind": "todo", "status": "Completed", "crossed": True})
    assert (x["status"], x["crossed"]) == ("Completed", "1")
    x = pq.upsert({"id": x["id"], "status": "Waitlist"})
    assert (x["status"], x["crossed"]) == ("Waitlist", "")
    # new items sort after older ones; reorder() sets a hand-made order and checks its input
    a, b = pq.upsert({"title": "A", "kind": "todo"}), pq.upsert({"title": "B", "kind": "todo"})
    assert int(a["sort"]) <= int(b["sort"])
    pq.reorder([b["id"], a["id"]])
    assert [r["sort"] for r in pq.load_tasks() if r["id"] in (b["id"], a["id"])] == ["1", "0"]
    for bad in (None, "x", [1]):
        try: pq.reorder(bad); assert False, bad
        except ValueError as e: assert str(e) == "invalid_order"
    assert pq.load_settings()["todo_done_last"] is True
    # a new child that starts in Ready takes its Waitlist parent along
    w = pq.upsert({"title": "W", "kind": "task", "status": "Waitlist"})
    pq.upsert({"title": "R", "kind": "todo", "parent": w["id"], "status": "Ready"})
    assert next(r["status"] for r in pq.load_tasks() if r["id"] == w["id"]) == "Ready"
    # dragging a Ready child under a Waitlist parent takes that parent along too
    w2, r2 = pq.upsert({"title": "W2", "kind": "task", "status": "Waitlist"}), pq.upsert({"title": "R2", "kind": "todo", "status": "Ready"})
    pq.upsert({"id": r2["id"], "parent": w2["id"]})
    assert next(r["status"] for r in pq.load_tasks() if r["id"] == w2["id"]) == "Ready"

def test_other_sites_refused_and_locked_files_lose_nothing():
    import pathlib
    tmp = _sandbox()
    srv = pq.ThreadingHTTPServer(("127.0.0.1", 0), pq.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_port
    def call(m, u, b=None, h={}):
        c = http.client.HTTPConnection("127.0.0.1", port)
        c.request(m, u, json.dumps(b).encode() if b is not None else None, {"Host": f"127.0.0.1:{port}", **h})
        r = c.getresponse(); return r.status, json.loads(r.read() or b"{}")
    # another website: a cross-site write, or DNS rebinding (its own name pointed at this computer) to read
    assert call("POST", "/api/tasks", {"title": "planted"}, {"Origin": "https://evil.example", "Content-Type": "text/plain"}) == (403, {"error": "forbidden"})
    assert call("GET", "/api/state", h={"Host": f"evil.example:{port}"})[0] == 403
    assert call("POST", "/api/photos/clear-finished", h={"Origin": "null"})[0] == 403
    assert pq.load_tasks() == []
    # the app's own page still works, with either address
    assert call("POST", "/api/tasks", {"title": "Mine", "status": "WIP"}, {"Origin": f"http://127.0.0.1:{port}"})[0] == 200
    assert call("GET", "/api/state", h={"Host": f"localhost:{port}"})[0] == 200
    t = pq.load_tasks()[0]
    # completed.csv open in Excel (Windows locks it): the save is refused before anything changes, and the page is told why
    real_open = pathlib.Path.open
    def locked(self, mode="r", *a, **k):
        if self.name == "completed.csv" and mode == "r+b": raise PermissionError(13, "in use")
        return real_open(self, mode, *a, **k)
    pq.save_tasks(pq.load_tasks())  # make sure completed.csv exists
    pathlib.Path.open = locked
    try:
        assert call("POST", "/api/tasks", {"id": t["id"], "status": "Completed"}) == (500, {"error": "file_locked"})
    finally:
        pathlib.Path.open = real_open
    assert [(r["title"], r["status"]) for r in pq.load_tasks()] == [("Mine", "WIP")]
    # a photo held open by another program can't be renamed: it keeps its old name and stays on the task
    t = pq.upsert({"id": t["id"], "photos": _upload(b"img")})
    real_rename = pathlib.Path.rename
    pathlib.Path.rename = lambda self, dst: (_ for _ in ()).throw(PermissionError(13, "in use"))
    try:
        done = pq.upsert({"id": t["id"], "status": "Completed"})
    finally:
        pathlib.Path.rename = real_rename
    assert done["status"] == "Completed" and pq.photo_file(done["photos"]) and pq.photo_file(done["photos"]).read_bytes() == b"img"
    srv.shutdown()
