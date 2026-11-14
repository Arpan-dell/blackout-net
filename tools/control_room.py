"""BLACKOUT NET control room: every node, every SOS with where its sender is, and the scout drone's live camera.

Node C (the HQ) prints its node table and every message it receives on its USB port. Get that here either way:
  node C plugged into this laptop:                 python tools/control_room.py --serial COM5
  node C riding on the gimbal drone, whose
  companion computer runs tools/hq_forward.py:     python tools/control_room.py --udp 15100
With the drones' GCS running on this laptop, also give   --gcs http://localhost:8765 --scout S-01
for the gimbal camera's live video, the map tiles, the scout's position and the "Send scout" button.
Add the relay drones and the node each carries, where node C rides, and the measured link range:
                                                   --relays I-01=B --hq-on-scout --range 1500
Nodes on drones are then shown at their drone's GPS position from the GCS.

No hardware at all (fake node C and fake GCS):     python tools/control_room.py --mock
Self-test:                                         python tools/control_room.py --selftest
Needs pyserial for --serial (pip install pyserial); everything else is the standard library.
"""
import argparse, collections, csv, datetime, http.server, json, math, os, socket, tempfile, threading, time
import urllib.request
import webbrowser

from monitor import Monitor, coord

HERE = os.path.dirname(os.path.abspath(__file__))
STALE_S = 15  # node C prints its table every 5 s; this long without one means the feed is lost
FILES = {"/": ("control_room.html", "text/html; charset=utf-8"),
         "/vendor/leaflet.js": ("vendor/leaflet.js", "text/javascript"),
         "/vendor/leaflet.css": ("vendor/leaflet.css", "text/css")}


def search_radius_m(phone_rssi):
    """Rough radius around the gateway node in which to look for the sender, from their phone's Wi-Fi signal there."""
    # shortcut: a fixed model (-40 dBm at 1 m, path-loss exponent 2.5, doubled for safety);
    # walk a phone away from node A once, note dBm against metres, and fit these two numbers if it matters.
    if not phone_rssi:
        return 100  # unknown (the node's own SOS button): anywhere within Wi-Fi reach of the node
    return round(min(150, max(10, 2 * 10 ** ((-40 - phone_rssi) / 25))))


def distance_m(lat1, lon1, lat2, lon2):
    la1, la2, dla, dlo = map(math.radians, (lat1, lat2, lat2 - lat1, lon2 - lon1))
    h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


# ---------------------------------------------------------------------------------------------- drone plan
PLAN_MARGIN = 0.8  # plan hops at 80 % of the link range, so a gust or a dip in signal does not break them


def dist(a, b):
    return distance_m(a["lat"], a["lon"], b["lat"], b["lon"])


def lerp(a, b, f):
    return {"lat": a["lat"] + (b["lat"] - a["lat"]) * f, "lon": a["lon"] + (b["lon"] - a["lon"]) * f}


def has_pos(p):
    return bool(p) and p.get("lat") is not None and p.get("lon") is not None


def plan_relays(hq, ground, range_m):
    """Hover points for relay drones so that every ground node reaches the HQ. Each node, nearest first, joins
    the closest point already linked (the HQ, a planned relay or a node already linked); relays go evenly
    along that straight line, no hop longer than PLAN_MARGIN of the range."""
    # shortcut: straight lines and one range for every hop; good for a few nodes in open ground,
    # a city with buildings needs measured links per site (tools/city_plan.py --range).
    reach = PLAN_MARGIN * range_m
    linked, relays, links = [hq], [], []
    for g in sorted(ground, key=lambda g: dist(hq, g)):
        p = min(linked, key=lambda c: dist(c, g))
        n = max(0, math.ceil(dist(p, g) / reach) - 1)
        prev = p
        for k in range(1, n + 1):
            q = dict(lerp(p, g, k / (n + 1)), serves=g["name"])
            relays.append(q)
            links.append((prev, q))
            linked.append(q)
            prev = q
        links.append((prev, g))
        linked.append(g)
    return relays, links


def route_breaks_at(start, end, mesh, range_m, steps=40):
    """Node C rides on the scout. Flying straight from start to end, is it always within range of some point
    of the mesh (ground nodes and relays)? Metres flown when the link first breaks, or None if it holds."""
    total = dist(start, end)
    for i in range(steps + 1):
        p = lerp(start, end, i / steps)
        if not any(dist(p, m) <= range_m for m in mesh):
            return round(total * i / steps)
    return None


def make_plan(hq, ground, relay_drones, drones, target, cfg):
    """Where each drone should be: relays to keep the mesh, and the scout's flight to the target."""
    plan = {"range_m": cfg["range_m"], "hq": hq, "relays": [], "links": [], "scout": None, "warnings": []}
    if not has_pos(hq):
        plan["warnings"].append("No HQ position yet: S-01's home from the GCS, or pos typed on node C.")
        return plan
    relays, links = plan_relays(hq, ground, cfg["range_m"])
    plan["links"] = [[[a["lat"], a["lon"]], [b["lat"], b["lon"]]] for a, b in links]
    for i, r in enumerate(relays):
        did, node = relay_drones[i] if i < len(relay_drones) else (None, None)
        live = drones.get(did) if did else None
        plan["relays"].append({**r, "n": i + 1, "drone": did, "node": node, "alt": cfg["relay_alt"],
                               "off_m": round(dist(live, r)) if has_pos(live) else None})
    if len(relays) > len(relay_drones):
        plan["warnings"].append(f"The mesh needs {len(relays)} relay drone(s) at {cfg['range_m']:g} m range; "
                                f"{len(relay_drones)} configured. Measure the real range, or move the HQ closer.")
    plan["spare"] = [{"drone": d, "node": n} for d, n in relay_drones[len(relays):]]
    if target:
        sc = drones.get(cfg["scout"])
        start = sc if has_pos(sc) else hq
        d = dist(start, target)
        mesh = ground + relays
        plan["scout"] = {"drone": cfg["scout"], "key": target["key"], "id": target["id"], "sent": bool(target.get("scout_sent")),
                         "lat": target["lat"], "lon": target["lon"], "distance_m": round(d),
                         "eta_s": round(d / cfg["speed"]), "breaks_at_m": route_breaks_at(start, target, mesh, cfg["range_m"])}
    if not ground:
        plan["warnings"].append("No ground node with a position yet.")
    return plan


class ControlRoom:
    """Node table (the monitor's), the message list kept on disk, and the scout drone's state.
    The reader thread, the GCS thread and the web page all go through mon.lock."""

    def __init__(self, mon, log_path, source, cfg=None):
        self.mon, self.log_path, self.source = mon, log_path, source
        self.msgs, self.lines = {}, collections.deque(maxlen=200)
        self.last_status, self.scout, self.scout_error = 0.0, None, ""
        self.drones = {}  # GCS id -> telemetry, for the scout and the relay drones
        self.cfg = cfg or {"range_m": 1500, "relay_alt": 40, "speed": 8, "scout": "S-01", "relays": [], "hq_on_scout": False}
        mon.error = f"Waiting for node C on {source}"
        if os.path.exists(log_path):  # node C forgets on every restart; the control room does not
            with open(log_path, encoding="utf-8") as f:
                for line in f:
                    try:
                        self._apply(json.loads(line))
                    except (ValueError, KeyError, TypeError):
                        pass  # a half-written last line after a crash

    def _apply(self, rec):
        if rec["kind"] == "msg":
            self.msgs.setdefault(rec["key"], rec["msg"])
        elif rec["key"] in self.msgs:
            self.msgs[rec["key"]][rec["kind"]] = rec["at"]  # "handled" or "scout_sent"

    def record(self, rec):
        self._apply(rec)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def feed(self, text):
        """One line from node C's USB port."""
        text = text.strip()
        try:
            if text.startswith("@NODES "):
                self.mon.ingest(json.loads(text[7:]))
                self.last_status = time.time()
            elif text.startswith("@MSG "):
                self.message(json.loads(text[5:]))
            elif text:
                self.lines.append(text)
        except (ValueError, KeyError, TypeError) as e:
            self.lines.append(f"(unreadable line from node C: {e!r}) {text[:120]}")

    def message(self, m):
        key = f"{m['origin']}-{m['message_id']}"
        if key in self.msgs:
            return
        lat, lon = coord(m, "lat", 90), coord(m, "lon", 180)
        if lat is None or lon is None:  # node C has not heard that node's position yet: use the last one seen here
            n = next((s["n"] for s in self.mon.stats.values() if s["n"]["name"] == m["origin"]), {})
            lat, lon = n.get("lat"), n.get("lon")
        rssi = m.get("phone_rssi")
        msg = {"key": key, "id": m["message_id"], "node": str(m["origin"]), "sos": m.get("type") == "SOS",
               "category": str(m.get("category", "other")), "text": str(m.get("text", "")),
               "landmark": str(m.get("landmark", "")), "via": m.get("via"), "phone_rssi": rssi,
               "lat": lat, "lon": lon, "radius_m": search_radius_m(rssi),
               "received_at": datetime.datetime.now().isoformat(timespec="seconds")}
        self.record({"kind": "msg", "key": key, "msg": msg})
        where = f" at {msg['landmark']}" if msg["landmark"] else ""
        self.mon.event("sos" if msg["sos"] else "msg", msg["node"],
                       f"{'SOS' if msg['sos'] else 'Message'} #{msg['id']} through node {msg['node']}: {msg['text']}{where}")

    def check_stale(self, now=None):
        now = now or time.time()
        if self.mon.link and now - self.last_status > STALE_S:
            self.mon.fail(f"nothing from node C for {STALE_S} s")

    def snapshot(self):
        """Call without holding mon.lock: Monitor.snapshot takes it itself."""
        st = self.mon.snapshot()
        st["self"] = dict(st["self"])  # the monitor's own dict: drone_positions must not change it
        with self.mon.lock:
            st["url"] = self.source
            st["messages"] = sorted((dict(m) for m in self.msgs.values()), key=lambda m: m["received_at"], reverse=True)
            st["lines"] = list(self.lines)[-60:]
            st["scout"], st["scout_error"] = self.scout, self.scout_error
            st["drones"] = dict(self.drones)
        self.drone_positions(st)
        st["plan"] = self.plan(st)
        return st

    def drone_positions(self, st):
        """Nodes riding on drones have no GPS of their own: their live position is the drone's, from the GCS."""
        carried = {node: did for did, node in self.cfg["relays"]}
        if self.cfg.get("hq_on_scout") and st["self"].get("name"):
            carried[st["self"]["name"]] = self.cfg["scout"]
        for n in [st["self"]] + st["nodes"]:
            d = st["drones"].get(carried.get(n.get("name")))
            if has_pos(d) and d.get("connected"):  # off the drone, or the drone is off: the typed position stays
                n["lat"], n["lon"], n["pos_src"] = d["lat"], d["lon"], f"drone {d['id']}"

    def plan(self, st):
        cfg = self.cfg
        sc = st["drones"].get(cfg["scout"]) or {}
        home = sc.get("home")
        hq = dict(home, source=f"{cfg['scout']} home") if has_pos(home) else \
            dict(lat=st["self"].get("lat"), lon=st["self"].get("lon"), source=f"node {st['self'].get('name', 'C')}")
        airborne = {st["self"].get("name")} | {node for _, node in cfg["relays"]}
        ground = [{"name": n["name"], "lat": n["lat"], "lon": n["lon"]} for n in st["nodes"]
                  if n["name"] not in airborne and has_pos(n)]
        open_ = [m for m in st["messages"] if not m.get("handled") and has_pos(m)]
        target = next((m for m in open_ if m.get("scout_sent")), None) or next((m for m in open_ if m["sos"]), None)
        return make_plan(hq, ground, cfg["relays"], st["drones"], target, cfg)


class Gcs:
    """The drones' ground control station: telemetry and the fly-to command, over its REST API."""

    def __init__(self, base, scout, alt, relay_ids=()):
        self.base, self.scout, self.alt, self.relay_ids = base.rstrip("/"), scout, alt, list(relay_ids)
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(self, path, body=None):
        req = urllib.request.Request(self.base + path, method="POST" if body is not None else "GET",
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with self.http.open(req, timeout=3) as r:
            return json.load(r)

    def drone(self, did):
        s = self.call(f"/api/drones/{did}")["snapshot"]
        g, home = s.get("gps") or {}, s.get("home") or {}
        d = {"id": did, "connected": bool(s.get("connected")), "armed": bool(s.get("armed")),
             "mode": s.get("flight_mode"), "lat": coord(g, "lat", 90), "lon": coord(g, "lon", 180),
             "alt_m": g.get("alt_rel_m"), "battery_pct": (s.get("battery") or {}).get("remaining_pct"),
             "home": {"lat": coord(home, "lat", 90), "lon": coord(home, "lon", 180)} if home else None}
        if d["lat"] == 0 and d["lon"] == 0:  # no GPS fix yet
            d["lat"] = d["lon"] = None
        return d

    def poll(self, room):
        while True:
            found, err = {}, ""
            for did in [self.scout] + self.relay_ids:
                try:
                    found[did] = self.drone(did)
                except Exception as e:  # GCS not started, or that drone not in its config
                    err = err or f"GCS at {self.base}, {did}: {e}"
            with room.mon.lock:
                room.drones, room.scout, room.scout_error = found, found.get(self.scout), err
            time.sleep(1)

    def goto(self, lat, lon, did=None, alt=None):
        return self.call(f"/api/drones/{did or self.scout}/goto",
                         {"lat": lat, "lon": lon, "alt": self.alt if alt is None else alt})


def read_serial(port, room):
    import serial  # pip install pyserial
    while True:
        try:
            s = serial.Serial()
            s.port, s.baudrate, s.timeout = port, 115200, 1
            s.dtr = s.rts = False  # opening the port must not restart node C: its inbox is in memory only
            s.open()
            with s:
                while True:
                    raw = s.readline()
                    if raw:
                        with room.mon.lock:
                            room.feed(raw.decode("utf-8", "replace"))
        except Exception as e:  # unplugged, or the wrong port: show it and keep trying
            with room.mon.lock:
                room.mon.fail(f"USB port {port}: {e}")
            time.sleep(2)


def read_udp(port, room):
    # shortcut: accepts lines from anyone on the drones' network; it is the team's own password-protected Wi-Fi.
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("0.0.0.0", port))
    while True:
        data, _ = s.recvfrom(65535)
        with room.mon.lock:
            for line in data.decode("utf-8", "replace").splitlines():
                room.feed(line)


def watchdog(room):
    while True:
        time.sleep(1)
        with room.mon.lock:
            room.check_stale()


def ui_server(room, gcs, port):
    class Handler(http.server.BaseHTTPRequestHandler):
        def send(self, code, body, kind="application/json"):
            if not isinstance(body, bytes):
                body = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/state":
                st = room.snapshot()
                st["gcs"] = gcs and {"base": gcs.base, "scout": gcs.scout, "alt": gcs.alt}
                return self.send(200, st)
            if self.path not in FILES:
                return self.send_error(404)
            name, kind = FILES[self.path]
            with open(os.path.join(HERE, name), "rb") as f:
                self.send(200, f.read(), kind)

        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 4096)))
                key = body["drone"] if self.path == "/api/relay" else body["key"]
            except (ValueError, KeyError, TypeError):
                return self.send(400, {"error": "send {\"key\": ...} or, for /api/relay, {\"drone\": ...}"})
            if self.path == "/api/relay":
                return self.fly_relay(key)
            with room.mon.lock:
                msg = dict(room.msgs.get(key) or {})
            if not msg:
                return self.send(404, {"error": "no such message"})
            at = datetime.datetime.now().isoformat(timespec="seconds")
            if self.path == "/api/handled":
                with room.mon.lock:
                    room.record({"kind": "handled", "key": key, "at": at})
                    room.mon.event("handled", msg["node"], f"#{msg['id']} marked handled")
                return self.send(200, {"ok": True})
            if self.path != "/api/scout":
                return self.send_error(404)
            if not gcs:
                return self.send(409, {"error": "Start the control room with --gcs to fly the scout"})
            if msg["lat"] is None:
                return self.send(409, {"error": f"Node {msg['node']} has no position: type pos <lat> <lon> on it over USB"})
            try:
                reply = gcs.goto(msg["lat"], msg["lon"])
            except Exception as e:
                return self.send(502, {"error": f"GCS did not take the command: {e}"})
            with room.mon.lock:
                if reply.get("ok"):
                    room.record({"kind": "scout_sent", "key": key, "at": at})
                room.mon.event("scout" if reply.get("ok") else "lost", msg["node"],
                               f"Scout {gcs.scout} sent to #{msg['id']} at {msg['lat']:.6f}, {msg['lon']:.6f}, "
                               f"{gcs.alt:g} m" if reply.get("ok") else
                               f"GCS refused to send {gcs.scout}: {reply}. Is it flying?")
            return self.send(200 if reply.get("ok") else 409, reply)

        def fly_relay(self, did):
            if not gcs:
                return self.send(409, {"error": "Start the control room with --gcs to fly the relay drones"})
            spot = next((r for r in room.snapshot()["plan"]["relays"] if r["drone"] == did), None)
            if not spot:
                return self.send(404, {"error": f"The plan has no hover point for {did} right now"})
            try:
                reply = gcs.goto(spot["lat"], spot["lon"], did, spot["alt"])
            except Exception as e:
                return self.send(502, {"error": f"GCS did not take the command: {e}"})
            with room.mon.lock:
                room.mon.event("scout" if reply.get("ok") else "lost", spot["node"] or did,
                               f"Relay {did} sent to hover point R{spot['n']} at {spot['lat']:.6f}, {spot['lon']:.6f}, "
                               f"{spot['alt']:g} m" if reply.get("ok") else f"GCS refused to send {did}: {reply}. Is it flying?")
            return self.send(200 if reply.get("ok") else 409, reply)

        def log_message(self, *a):
            pass

    return http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)  # this laptop only: it can fly a drone


# ---------------------------------------------------------------------------------------------- mock
def mock(room, gcs_port):
    """Fake node C on the gimbal drone, and a fake GCS whose scout flies to wherever it is sent."""
    home, a_pos = (28.7105, 77.2135), (28.7245, 77.2295)  # A about 2.1 km from the control room: needs a relay
    fleet = {did: {"lat": home[0], "lon": home[1], "target": None} for did in ("S-01", "I-01")}
    sc, relay = fleet["S-01"], fleet["I-01"]  # node C rides on S-01, node B on I-01
    t0 = time.time()

    def step():  # called every 5 s: the scout covers 40 m (8 m/s), the lighter relay drone 60 m
        for did, d in fleet.items():
            if d["target"]:
                left = distance_m(d["lat"], d["lon"], *d["target"])
                f = min(1, (60 if did == "I-01" else 40) / left) if left > 0.5 else 1
                d["lat"] += (d["target"][0] - d["lat"]) * f
                d["lon"] += (d["target"][1] - d["lon"]) * f

    class FakeGcs(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/api/drones/") and self.path.split("/")[3] in fleet:
                d = fleet[self.path.split("/")[3]]
                body = json.dumps({"snapshot": {"connected": True, "armed": True, "flight_mode": "GUIDED" if d["target"] else "LOITER",
                                                "gps": {"lat": d["lat"], "lon": d["lon"], "alt_rel_m": 40.0},
                                                "home": {"lat": home[0], "lon": home[1], "alt_msl_m": 216.0},
                                                "battery": {"remaining_pct": 81}}}).encode()
                kind = "application/json"
            elif self.path.startswith("/video/"):
                body = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360"><rect width="640" height="360" fill="#203040"/>'
                        b'<text x="320" y="170" fill="#fff" font-size="28" text-anchor="middle" font-family="sans-serif">MOCK CAMERA</text>'
                        b'<text x="320" y="210" fill="#9ab" font-size="16" text-anchor="middle" font-family="sans-serif">'
                        b'the GCS shows the ZR10 stream here</text></svg>')
                kind = "image/svg+xml"
            else:
                return self.send_error(404)
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            b = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            fleet[self.path.split("/")[3]]["target"] = (b["lat"], b["lon"])
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", gcs_port), FakeGcs)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def node_c():
        sent = set()
        while True:
            up = time.time() - t0
            step()
            b_pos = (relay["lat"], relay["lon"])
            seq = int(up // 10)
            nodes = [{"id": 1, "name": "A", "age_ms": int(up % 10 * 1000), "seq": seq, "via": "B", "rssi": -96 - seq % 5,
                      "snr": 4.5, "uptime_s": int(up) + 600, "lat": a_pos[0], "lon": a_pos[1]},
                     {"id": 2, "name": "B", "age_ms": int((up + 4) % 10 * 1000), "seq": int((up + 4) // 10), "via": "B",
                      "rssi": -78 - seq % 4, "snr": 9.0, "uptime_s": int(up) + 300, "lat": b_pos[0], "lon": b_pos[1]}]
            lines = ["@NODES " + json.dumps({"self": {"name": "C", "uptime_s": int(up), "wifi_clients": 0, "lat": sc["lat"],
                                                      "lon": sc["lon"], "pos_src": "saved"},
                                             "hb_interval_s": 10, "nodes": nodes})]
            for at, mid_, sos, text, mark, rssi in ((8, 7001, True, "2 hurt, 1 bleeding", "school gate", -71),
                                                    (30, 7002, False, "need drinking water", "temple", -58),
                                                    (75, 7003, True, "SOS button pressed", "Node A", 0)):
                if up >= at and mid_ not in sent:
                    sent.add(mid_)
                    m = {"message_id": mid_, "origin": "A", "type": "SOS" if sos else "NORMAL", "category": "medical",
                         "text": text, "landmark": mark, "age_ms": 0, "via": "B", "rssi": -97, "snr": 4.0,
                         "acknowledged": False, "lat": a_pos[0], "lon": a_pos[1]}
                    if rssi:
                        m["phone_rssi"] = rssi
                    lines.append("@MSG " + json.dumps(m))
                    lines.append(f"[{int(up * 1000):8d} ms] INBOX #{mid_} from A {'SOS' if sos else 'normal'} \"{text}\"")
            with room.mon.lock:
                for line in lines:
                    room.feed(line)
            time.sleep(5 if up > 2 else 1)

    threading.Thread(target=node_c, daemon=True).start()


# ---------------------------------------------------------------------------------------------- self-test
def selftest():
    assert search_radius_m(None) == 100 and search_radius_m(0) == 100
    assert search_radius_m(-55) == 10 and search_radius_m(-70) == 32 and search_radius_m(-95) == 150
    assert abs(distance_m(28.75, 77.116, 28.75, 77.118) - 195) < 1
    # drone plan: 2.2 km needs one relay at 1500 m range (hops of at most 1200 m); 500 m needs none
    north = lambda m, east=0: {"lat": 28.70 + m / 111195, "lon": 77.20 + east / (111195 * math.cos(math.radians(28.7)))}
    hq, far, near = north(0), dict(north(2200), name="A"), dict(north(500), name="A")
    relays, links = plan_relays(hq, [far], 1500)
    assert len(relays) == 1 and abs(dist(relays[0], north(1100))) < 1 and len(links) == 2, relays
    assert plan_relays(hq, [near], 1500)[0] == []
    twin = dict(north(2200, 300), name="D")  # next to A: joins A, no second relay
    assert len(plan_relays(hq, [far, twin], 1500)[0]) == 1
    assert route_breaks_at(hq, far, [far] + relays, 1500) is None  # node C stays linked all the way
    assert route_breaks_at(hq, far, [far], 1500) == 0               # without the relay it starts cut off
    cfg = {"range_m": 1500, "relay_alt": 40, "speed": 8, "scout": "S-01", "relays": [("I-01", "B")]}
    p = make_plan(hq, [far], cfg["relays"], {"I-01": dict(hq)}, dict(far, key="A-1", id=1), cfg)
    assert p["relays"][0]["drone"] == "I-01" and p["relays"][0]["off_m"] == 1100 and not p["warnings"], p
    assert p["scout"]["distance_m"] == 2200 and p["scout"]["eta_s"] == 275 and p["scout"]["breaks_at_m"] is None
    assert make_plan(hq, [far], [], {}, None, cfg)["warnings"]  # a relay needed and no drone for it
    path = os.path.join(tempfile.mkdtemp(), "messages.jsonl")
    room = ControlRoom(Monitor("usb"), path, "COM9")
    status = {"self": {"name": "C", "uptime_s": 5, "wifi_clients": 0, "lat": 28.71, "lon": 77.21},
              "hb_interval_s": 30,
              "nodes": [{"id": 1, "name": "A", "age_ms": 100, "seq": 4, "via": "B", "rssi": -90, "snr": 5, "uptime_s": 9,
                         "lat": 28.72, "lon": 77.22}]}
    room.feed("@NODES " + json.dumps(status))
    assert room.mon.link and room.snapshot()["nodes"][0]["name"] == "A"
    sos = {"message_id": 7, "origin": "A", "type": "SOS", "text": 'say "hi"', "landmark": "gate", "phone_rssi": -70,
           "lat": 28.7201, "lon": 77.2202}
    room.feed("@MSG " + json.dumps(sos))
    room.feed("@MSG " + json.dumps(sos))  # the same message twice: kept once
    no_pos = {"message_id": 8, "origin": "A", "type": "NORMAL", "text": "water"}
    room.feed("@MSG " + json.dumps(no_pos))  # node C had no position for A: the last one seen here is used
    room.feed("@MSG {broken")
    room.feed("[  1234 ms] RX HB #4")
    msgs = {m["id"]: m for m in room.snapshot()["messages"]}
    assert len(msgs) == 2 and msgs[7]["sos"] and msgs[7]["text"] == 'say "hi"' and msgs[7]["radius_m"] == 32, msgs
    assert (msgs[7]["lat"], msgs[8]["lat"], msgs[8]["radius_m"]) == (28.7201, 28.72, 100), msgs
    assert room.lines[-1] == "[  1234 ms] RX HB #4" and "unreadable" in room.lines[-2]
    assert [e["kind"] for e in room.mon.events][-2:] == ["sos", "msg"]
    plan = room.snapshot()["plan"]  # C at 28.71/77.21, A about 1.45 km away: one relay, no drone named for it
    assert len(plan["relays"]) == 1 and plan["warnings"] and plan["scout"]["id"] == 7, plan
    # nodes on drones show at the drone's live position (here A pretends to ride on I-01, C on S-01)
    room.cfg = dict(room.cfg, relays=[("I-01", "A")], hq_on_scout=True)
    room.drones = {"I-01": {"id": "I-01", "connected": True, "lat": 28.73, "lon": 77.23},
                   "S-01": {"id": "S-01", "connected": True, "lat": 28.70, "lon": 77.20}}
    st = room.snapshot()
    assert (st["nodes"][0]["lat"], st["nodes"][0]["pos_src"], st["self"]["lat"]) == (28.73, "drone I-01", 28.70), st
    room.drones["I-01"]["connected"] = False  # drone not connected: the node's typed position is used
    assert room.snapshot()["nodes"][0]["lat"] == 28.72
    room.cfg, room.drones = dict(room.cfg, relays=[], hq_on_scout=False), {}
    assert room.snapshot()["nodes"][0]["lat"] == 28.72  # the node's own (typed) position again
    room.record({"kind": "handled", "key": "A-7", "at": "t"})
    again = ControlRoom(Monitor("usb"), path, "COM9")  # a restart keeps the messages and what was done
    assert len(again.msgs) == 2 and again.msgs["A-7"]["handled"] == "t"
    srv = ui_server(room, None, 0)  # the page's own request path, with its locking
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            f"http://127.0.0.1:{srv.server_address[1]}/state", timeout=3) as r:
        assert len(json.load(r)["messages"]) == 2
    srv.shutdown()
    room.check_stale(time.time() + STALE_S + 1)
    assert not room.mon.link and room.snapshot()["nodes"][0]["status"] == "UNKNOWN"
    print("selftest ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--serial", metavar="PORT", help="node C on this laptop's USB, e.g. COM5 or /dev/ttyUSB0")
    src.add_argument("--udp", type=int, metavar="PORT", help="node C's lines forwarded by tools/hq_forward.py")
    src.add_argument("--mock", action="store_true", help="fake node C and fake GCS, no hardware")
    ap.add_argument("--gcs", metavar="URL", help="the drones' GCS, e.g. http://localhost:8765")
    ap.add_argument("--scout", default="S-01", help="GCS id of the gimbal-camera drone (default S-01)")
    ap.add_argument("--scout-alt", type=float, default=40, help="height above home the scout flies to, metres")
    ap.add_argument("--scout-speed", type=float, default=8, help="the scout's cruise speed in m/s, for the flight time")
    ap.add_argument("--relays", default="", metavar="DRONE=NODE,...",
                    help="relay drones in the GCS and the node each carries, e.g. I-01=B")
    ap.add_argument("--relay-alt", type=float, default=40, help="height above home the relay drones hover at, metres")
    ap.add_argument("--hq-on-scout", action="store_true",
                    help="node C rides on the scout: show it at the scout's live position")
    ap.add_argument("--range", type=float, default=1500,
                    help="metres one LoRa link covers (measure it with relay_compare.py); hops are planned at 80 %%")
    ap.add_argument("--messages", default="messages.jsonl", help="every message and what was done about it")
    ap.add_argument("--csv", default="heartbeats.csv", help="every heartbeat is appended here")
    ap.add_argument("--port", type=int, default=8780, help="port of the control room page on this laptop")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not (a.serial or a.udp or a.mock):
        ap.error("give --serial PORT, --udp PORT or --mock")
    if a.mock:
        a.gcs, a.messages = a.gcs or "http://127.0.0.1:8799", os.path.join(tempfile.mkdtemp(), "messages.jsonl")
        a.relays, a.hq_on_scout = a.relays or "I-01=B", True
    try:
        relays = [tuple(x.strip() for x in pair.split("=")) for pair in a.relays.split(",") if pair.strip()]
        assert all(len(r) == 2 and all(r) for r in relays)
    except AssertionError:
        ap.error("--relays looks like I-01=B,I-02=D: the GCS id of each relay drone and the node it carries")
    cfg = {"range_m": a.range, "relay_alt": a.relay_alt, "speed": a.scout_speed, "scout": a.scout, "relays": relays,
           "hq_on_scout": a.hq_on_scout}

    new_file = not os.path.exists(a.csv)
    out = open(a.csv, "a", newline="")
    rows = csv.writer(out)
    if new_file:
        rows.writerow(["received_at", "node", "seq", "via", "rssi", "snr"])

    def write_row(row):
        rows.writerow(row)
        out.flush()

    source = f"USB {a.serial}" if a.serial else f"UDP port {a.udp}" if a.udp else "mock node C"
    room = ControlRoom(Monitor(source, write_row, os.path.abspath(a.csv)), a.messages, source, cfg)
    gcs = Gcs(a.gcs, a.scout, a.scout_alt, [d for d, _ in relays]) if a.gcs else None
    try:
        srv = ui_server(room, gcs, a.port)
    except OSError:
        raise SystemExit(f"Port {a.port} is busy. Is the control room already running? Otherwise add --port {a.port + 1}")
    if a.mock:
        mock(room, 8799)
    elif a.serial:
        threading.Thread(target=read_serial, args=(a.serial, room), daemon=True).start()
    else:
        threading.Thread(target=read_udp, args=(a.udp, room), daemon=True).start()
    threading.Thread(target=watchdog, args=(room,), daemon=True).start()
    if gcs:
        threading.Thread(target=gcs.poll, args=(room,), daemon=True).start()
    page = f"http://127.0.0.1:{a.port}/"
    print(f"Control room: {page}   messages: {os.path.abspath(a.messages)}   (Ctrl+C to stop)")
    webbrowser.open(page)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
