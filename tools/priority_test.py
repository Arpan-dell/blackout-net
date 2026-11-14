"""Measure what SOS priority gains over plain FIFO, on the real radios.

Join node A's Wi-Fi (BLACKOUT_A), make sure B and C are running, then:   python priority_test.py
It queues 20 normal messages followed by 3 SOS messages, once with priority on and once with it off,
and prints the delivery count and median delay of each class. Takes about 4 minutes.
One run is one sample: repeat it, and report the conditions (distance, antennas, radio settings).
"""
import json, os, re, statistics, sys, time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://192.168.4.1"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # a campus proxy cannot reach 192.168.4.1
CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "firmware", "include", "config.h")
PIN = re.search(r'#define COORD_PIN "([^"]*)"', open(CONFIG, encoding="utf-8").read())[1]  # same PIN on every node


def call(path, body=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    path += ("&" if "?" in path else "?") + "pin=" + PIN  # lifts the 3-per-phone limit and unlocks /api/mode
    req = urllib.request.Request(BASE + path, data, {"Content-Type": "application/json"}, method=method)
    with opener.open(req, timeout=5) as r:
        return json.load(r)


def summary(msgs):
    done = [m["latency_ms"] / 1000 for m in msgs if m["status"] == "delivered"]
    return f"{len(done)} of {len(msgs)} delivered" + (f", median delay {statistics.median(done):.1f} s" if done else "")


def run(priority):
    call(f"/api/mode?priority={priority}", method="POST")
    ids = {}
    for kind, n in (("NORMAL", 20), ("SOS", 3)):
        for i in range(n):
            r = call("/api/send", {"destination": "HQ", "type": kind, "category": "other", "text": f"test {kind} {i}"})
            ids[r["message_id"]] = kind
    while True:  # every message ends as delivered or expired, so this ends too
        time.sleep(3)
        ours = [m for m in call("/api/messages")["outbox"] if m["message_id"] in ids]
        left = sum(m["status"] not in ("delivered", "expired") for m in ours)
        print(f"  {left} still on their way", end="\r")
        if not left:
            break
    print(f"priority {'ON ' if priority else 'OFF (FIFO)'}")
    for kind in ("SOS", "NORMAL"):
        print(f"  {kind:<6} {summary([m for m in ours if ids[m['message_id']] == kind])}")


if __name__ == "__main__":
    run(1)
    run(0)
    call("/api/mode?priority=1", method="POST")
