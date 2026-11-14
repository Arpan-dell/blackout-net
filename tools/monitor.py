"""BLACKOUT NET node monitor: a live dashboard of which nodes are alive and every heartbeat as it arrives.

Join the node's Wi-Fi (BLACKOUT_A or BLACKOUT_C), then:   python monitor.py
No hardware yet (fake node on this laptop):                python monitor.py --mock

The dashboard (dashboard.html, next to this file) opens in your browser. This script polls
GET http://192.168.4.1/api/nodes and the firmware must answer with:

{"self": {"name": "A", "uptime_s": 321, "wifi_clients": 2, "lat": 28.7499, "lon": 77.1164},
 "hb_interval_s": 30,
 "nodes": [{"id": 3, "name": "C", "age_ms": 1200, "seq": 41, "via": "B",
            "rssi": -88, "snr": 7.5, "uptime_s": 300, "lat": 28.7501, "lon": 77.1202}]}

age_ms  ms since this node last heard that node's heartbeat (the ESP32 has no clock, so it sends an age)
seq     heartbeat counter set by the far node; gaps in it are lost heartbeats
via     node that handed the packet to this one ("B" when relayed, the node's own name when direct)
rssi/snr  of that last hop only
lat/lon   optional GPS position in degrees; leave out (or null) for a node with no position set.
          With a position for every node the map is drawn to scale and shows distances.
"""
import argparse, collections, csv, datetime, http.server, json, os, random, threading, time
import urllib.request
import webbrowser


def track(stats, n):
    """Record one polled node entry. None if this heartbeat was already seen, else how many were lost just before it."""
    # shortcut: heartbeats that arrive while this laptop is off the Wi-Fi count as lost,
    # move the counting into the firmware if the Received % goes into the test report.
    s, seq = stats.setdefault(n["id"], {}), n["seq"]
    if not s or seq < s["last"]:  # first sight, or the far node rebooted and restarted its counter
        s.update(first=seq, last=seq, got=1)
        return 0
    if seq == s["last"]:
        return None
    gap = seq - s["last"] - 1
    s["last"], s["got"] = seq, s["got"] + 1
    return gap


def coord(d, key, limit):
    """Optional GPS field: None when the node has no position set or sends a value that cannot be one."""
    v = d.get(key)
    if v is None:
        return None
    v = float(v)
    return v if abs(v) <= limit else None


def received_pct(s):
    return 100 * s["got"] / (s["last"] - s["first"] + 1)


class Monitor:
    """Everything the dashboard shows. The poll thread writes it, the web page reads snapshot()."""

    def __init__(self, url, write_row=None, csv_path=""):
        self.url, self.write_row, self.csv_path = url, write_row, csv_path
        self.lock = threading.Lock()
        self.link, self.error, self.me, self.interval, self.polled = None, "Connecting...", {}, 30.0, 0.0
        self.stats, self.events, self.eid = {}, collections.deque(maxlen=300), 0

    def event(self, kind, node, text, at=None):
        self.eid += 1
        self.events.append({"id": self.eid, "t": f"{at or datetime.datetime.now():%H:%M:%S}",
                            "kind": kind, "node": node, "text": text})

    def ingest(self, data):
        """Fold one /api/nodes reply into the state. Raises KeyError/TypeError/ValueError if it has the wrong shape."""
        me = {"name": str(data["self"]["name"]), "uptime_s": int(data["self"]["uptime_s"]),
              "wifi_clients": int(data["self"]["wifi_clients"]),
              "lat": coord(data["self"], "lat", 90), "lon": coord(data["self"], "lon", 180),
              "pos_src": data["self"].get("pos_src"), "gps_age_s": data["self"].get("gps_age_s")}
        interval = float(data["hb_interval_s"])
        if interval <= 0:
            raise ValueError("hb_interval_s must be above 0")
        now = datetime.datetime.now()
        for raw in data["nodes"]:
            n = {"id": raw["id"], "name": str(raw["name"]), "via": str(raw["via"]), "age_ms": int(raw["age_ms"]),
                 "seq": int(raw["seq"]), "rssi": float(raw["rssi"]), "snr": float(raw["snr"]),
                 "uptime_s": int(raw["uptime_s"]), "lat": coord(raw, "lat", 90), "lon": coord(raw, "lon", 180)}
            name, seq = n["name"], n["seq"]
            before = self.stats.get(n["id"], {}).get("last")
            gap = track(self.stats, n)
            s = self.stats[n["id"]]
            if before is None and self.polled:  # not on the first reply, where every node is new
                self.event("new", name, f"New node {name} joined the network")
            if gap is not None:
                at = now - datetime.timedelta(milliseconds=n["age_ms"])
                s.setdefault("hist", collections.deque(maxlen=60)).append(n["rssi"])
                if self.write_row:
                    self.write_row([at.isoformat(timespec="seconds"), name, seq, n["via"], n["rssi"], n["snr"]])
                if before is not None and seq < before:
                    self.event("restart", name, f"{name} restarted (its heartbeat counter went back to #{seq})", at)
                if gap:
                    self.event("lost", name, f"{gap} heartbeat(s) from {name} lost (#{seq - gap} to #{seq - 1})", at)
                self.event("hb", name, f"Heartbeat #{seq} from {name} via {n['via']}, "
                                       f"RSSI {n['rssi']:g} dBm, SNR {n['snr']:g} dB", at)
            online = n["age_ms"] <= 3 * interval * 1000
            if s.get("online") not in (None, online):
                self.event("online" if online else "offline", name, f"{name} is back ONLINE" if online
                           else f"{name} went OFFLINE (silent for {n['age_ms'] / 1000:.0f} s)")
            s["online"], s["n"] = online, n
        if self.link is False:
            self.event("link", "", "Link to the node restored")
        self.link, self.error, self.me, self.interval, self.polled = True, "", me, interval, time.time()

    def fail(self, text):
        if self.link:
            self.event("link", "", f"Link to the node lost: {text}")
        self.link, self.error = False, text

    def snapshot(self):
        with self.lock:
            drift = (time.time() - self.polled) * 1000 if self.polled else 0  # ages keep ticking between polls
            nodes = []
            for s in self.stats.values():
                age = s["n"]["age_ms"] + drift
                status = "UNKNOWN" if not self.link else "ONLINE" if age <= 3 * self.interval * 1000 else "OFFLINE"
                nodes.append({**s["n"], "age_ms": int(age), "status": status, "received": s["got"],
                              "lost": s["last"] - s["first"] + 1 - s["got"],
                              "received_pct": round(received_pct(s)), "rssi_hist": list(s["hist"])})
            return {"link": bool(self.link), "error": self.error, "url": self.url, "self": self.me,
                    "hb_interval_s": self.interval, "nodes": nodes, "events": list(self.events),
                    "csv": self.csv_path}


def poll(mon):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # a campus proxy cannot reach 192.168.4.1
    while True:
        try:
            with opener.open(mon.url, timeout=2) as r:
                data = json.load(r)
            with mon.lock:
                mon.ingest(data)
        except (KeyError, TypeError, ValueError) as e:
            with mon.lock:
                mon.fail(f"the node sent a reply in the wrong shape ({e!r})")
        except Exception as e:  # node off or wrong Wi-Fi: show it and keep trying
            with mon.lock:
                mon.fail(str(e))
        time.sleep(1.5)


def ui_server(mon, port):
    page = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/state":
                body, kind = json.dumps(mon.snapshot()).encode(), "application/json"
            elif self.path == "/":
                with open(page, "rb") as f:
                    body, kind = f.read(), "text/html; charset=utf-8"
            else:
                return self.send_error(404)
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    return http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)  # this laptop only, not the node's Wi-Fi


def mock_server(port):
    """Fake node A. B is always up; C beats through B and goes silent for 15 s of every minute;
    D is switched on 20 s after the start, to show a node joining."""
    t0 = time.time()

    def beat(up, dead):
        t = up - up % 60 + 30 if dead else up  # frozen at the moment it died
        return int(t // 3), int((up - t + t % 3) * 1000)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            up = time.time() - t0
            nodes = []
            for i, name, via, rssi, lat, lon in ((2, "B", "B", -62, 28.75050, 77.11830),
                                                 (3, "C", "B", -64, 28.75010, 77.12020),
                                                 (4, "D", "D", -75, 28.74870, 77.11800)):
                if name == "D" and up < 20:
                    continue
                seq, age = beat(up, name == "C" and 30 <= up % 60 < 45)
                random.seed(i * 100000 + seq)  # one RSSI per heartbeat, not per poll
                nodes.append({"id": i, "name": name, "age_ms": age, "seq": seq, "via": via,
                              "rssi": rssi + random.randint(-6, 6), "snr": 9.0 + random.randint(-2, 2) / 2,
                              "uptime_s": int(up), "lat": lat, "lon": lon})
            body = json.dumps({"self": {"name": "A", "uptime_s": int(up), "wifi_clients": 1,
                                        "lat": 28.74990, "lon": 77.11640},
                               "hb_interval_s": 3, "nodes": nodes}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def selftest():
    st = {}
    assert track(st, {"id": 3, "seq": 10}) == 0
    assert track(st, {"id": 3, "seq": 10}) is None  # same heartbeat polled twice
    assert track(st, {"id": 3, "seq": 13}) == 2  # 11 and 12 were lost
    assert received_pct(st[3]) == 50
    assert track(st, {"id": 3, "seq": 0}) == 0 and received_pct(st[3]) == 100  # reboot starts a fresh count

    def reply(seq, age):
        return {"self": {"name": "A", "uptime_s": 1, "wifi_clients": 0}, "hb_interval_s": 3,
                "nodes": [{"id": 3, "name": "C", "via": "B", "age_ms": age, "seq": seq, "rssi": -80, "snr": 7,
                           "uptime_s": 1}]}

    m = Monitor("test")
    for seq, age in ((1, 0), (1, 9500), (4, 100)):  # heard, silent past 3 intervals, back with 2 lost
        m.ingest(reply(seq, age))
    kinds = [e["kind"] for e in m.events]
    assert kinds == ["hb", "offline", "lost", "hb", "online"], kinds
    node = m.snapshot()["nodes"][0]
    assert node["lost"] == 2 and node["status"] == "ONLINE" and node["rssi_hist"] == [-80, -80], node
    joined = reply(4, 100)
    joined["nodes"].append({"id": 4, "name": "D", "via": "D", "age_ms": 0, "seq": 1, "rssi": -70, "snr": 8,
                            "uptime_s": 1, "lat": 28.75, "lon": 999})
    m.ingest(joined)
    assert [e["kind"] for e in m.events][-2:] == ["new", "hb"]
    d = m.snapshot()["nodes"][1]
    assert d["lat"] == 28.75 and d["lon"] is None, d  # a value that cannot be a longitude counts as no position
    try:
        m.ingest({"self": {}})
        assert False, "a reply in the wrong shape must be rejected"
    except KeyError:
        pass
    m.fail("gone")
    assert m.snapshot()["nodes"][0]["status"] == "UNKNOWN" and m.events[-1]["kind"] == "link"
    print("selftest ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--url", default="http://192.168.4.1/api/nodes")
    ap.add_argument("--mock", action="store_true", help="run against a fake node on this laptop")
    ap.add_argument("--csv", default="heartbeats.csv", help="every heartbeat is appended here")
    ap.add_argument("--port", type=int, default=8770, help="port of the dashboard on this laptop")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.mock:
        mock_server(8765)
        a.url = "http://127.0.0.1:8765/api/nodes"

    new_file = not os.path.exists(a.csv)
    out = open(a.csv, "a", newline="")
    rows = csv.writer(out)
    if new_file:
        rows.writerow(["received_at", "node", "seq", "via", "rssi", "snr"])

    def write_row(row):
        rows.writerow(row)
        out.flush()

    mon = Monitor(a.url, write_row, os.path.abspath(a.csv))
    try:
        srv = ui_server(mon, a.port)
    except OSError:
        raise SystemExit(f"Port {a.port} is busy. Is the monitor already running? Otherwise add --port {a.port + 1}")
    threading.Thread(target=poll, args=(mon,), daemon=True).start()
    page = f"http://127.0.0.1:{a.port}/"
    print(f"Dashboard: {page}   (Ctrl+C to stop)")
    webbrowser.open(page)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
