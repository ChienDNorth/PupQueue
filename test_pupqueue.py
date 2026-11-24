import json, tempfile, threading, urllib.request
from pathlib import Path
import pupqueue as pq

def test_duration():
    assert pq.format_duration(pq.parse_duration("70min")) == "1h10min"
    assert pq.format_duration(pq.parse_duration("0.5h")) == "30min"
    assert pq.format_duration(pq.parse_duration("24h")) == "1d"
    assert pq.parse_duration("1d2h") == 1560 and pq.parse_duration("") == ""
    for bad in ("abc", "5x", "h"):
        try: pq.parse_duration(bad); assert False
        except ValueError: pass

def test_storage_and_api():
    tmp = Path(tempfile.mkdtemp())
    pq.RECORDS, pq.PHOTOS, pq.SETTINGS_FILE = tmp / "task records", tmp / "photos", tmp / "s.json"
    srv = pq.ThreadingHTTPServer(("127.0.0.1", 0), pq.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    def call(m, u, b=None, h={}):
        data = b if isinstance(b, bytes) else json.dumps(b).encode() if b is not None else None
        try: return json.load(urllib.request.urlopen(urllib.request.Request(base + u, data, h, method=m)))
        except urllib.error.HTTPError as e: return {"status": e.code, **json.load(e)}
    a = call("POST", "/api/tasks", {"title": "Cmsn", "type": "Commission", "estimate": "70min", "price": "50"})
    b = call("POST", "/api/tasks", {"title": "Gift", "type": "Gift", "client_socials": [{"net": "QQ", "handle": "1"}]})
    assert a["status"] == "Waitlist" and b["status"] == "Ready" and a["estimate"] == "1h10min"
    call("POST", "/api/tasks", {"id": a["id"], "status": "Completed"})
    assert "Cmsn" in (pq.RECORDS / "completed.csv").read_text("utf-8-sig")
    assert "Cmsn" not in (pq.RECORDS / "active.csv").read_text("utf-8-sig")
    assert call("POST", "/api/tasks", {"title": ""})["status"] == 400
    assert call("POST", "/api/tasks", {"title": "x", "price": "abc"})["status"] == 400
    p = call("POST", "/api/upload", b"img", {"X-Filename": "a.png"})["path"]
    assert (tmp / p).read_bytes() == b"img"
    state = call("GET", "/api/state")
    assert len(state["tasks"]) == 2 and "en" in state["languages"]
    call("DELETE", f"/api/tasks/{b['id']}")
    assert len(call("GET", "/api/state")["tasks"]) == 1
