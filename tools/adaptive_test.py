"""Phase 2 only: measure what adaptive spreading factor gains over the fixed SF, on the real radios.

Keep the nodes in the same places for every run. Then:
  1. On the HQ's Network tab (phone on BLACKOUT_C), set "Adaptive SF" off. Wait until node A shows SF9.
  2. Laptop on BLACKOUT_A:   python adaptive_test.py fixed
  3. On the HQ, set "Adaptive SF" on. Wait until node A shows the SF the HQ chose, with no switch pending.
  4. Laptop on BLACKOUT_A:   python adaptive_test.py adaptive
Each run sends 20 messages from node A and prints how many were delivered, the median delay, and how much
air time node A used per delivered message. Results are added to adaptive_results.csv.
One run is one sample: repeat each a few times, and write down distances and antennas with the numbers.
"""
import csv, datetime, json, os, re, statistics, sys, time
import urllib.request

BASE = "http://192.168.4.1"
COUNT = 20
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # a campus proxy cannot reach 192.168.4.1
CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "firmware-phase2", "include", "config.h")
PIN = re.search(r'#define COORD_PIN "([^"]*)"', open(CONFIG, encoding="utf-8").read())[1]  # same PIN on every node


def call(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    path += ("&" if "?" in path else "?") + "pin=" + PIN  # lifts the 3-per-phone limit for the 20 test messages
    req = urllib.request.Request(BASE + path, data, {"Content-Type": "application/json"})
    with opener.open(req, timeout=5) as r:
        return json.load(r)


def main():
    label = sys.argv[1] if len(sys.argv) > 1 else "run"
    before = call("/api/status")
    ad = before["adaptive"]
    if ad.get("switch_to_sf") is not None or ad["scanning"]:
        raise SystemExit("Node A is changing SF right now. Wait until its Network tab shows no switch, then run again.")
    if before["role"] == "hq":
        raise SystemExit("Connected to the HQ. Join BLACKOUT_A and run again.")
    sf = ad["sf"]
    print(f"{label}: sending {COUNT} messages from node {before['node']} on SF{sf}")
    ids = set()
    for i in range(COUNT):
        ids.add(call("/api/send", {"destination": "HQ", "type": "NORMAL", "category": "other", "text": f"{label} {i}"})["message_id"])
    start = time.time()
    while True:  # every message ends as delivered or expired, so this ends too
        time.sleep(3)
        ours = [m for m in call("/api/messages")["outbox"] if m["message_id"] in ids]
        left = sum(m["status"] not in ("delivered", "expired") for m in ours)
        print(f"  {left} still on their way", end="\r")
        if not left:
            break
    after = call("/api/status")
    done = [m["latency_ms"] / 1000 for m in ours if m["status"] == "delivered"]
    air = (after["airtime_ms_total"] - before["airtime_ms_total"]) / 1000
    median = statistics.median(done) if done else None
    print(f"{label}: SF{sf}, {len(done)} of {len(ours)} delivered in {time.time() - start:.0f} s" +
          (f", median delay {median:.1f} s, node A air time {air / len(done):.2f} s per delivered message" if done else ""))
    if after["adaptive"]["sf"] != sf:
        print(f"WARNING: the SF changed during the run (SF{sf} -> SF{after['adaptive']['sf']}). Do not use this run.")
    new = not os.path.exists("adaptive_results.csv")
    with open("adaptive_results.csv", "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "label", "sf", "sent", "delivered", "median_delay_s", "air_s_per_delivered", "sf_changed"])
        w.writerow([datetime.datetime.now().isoformat(timespec="seconds"), label, sf, len(ours), len(done),
                    f"{median:.2f}" if done else "", f"{air / len(done):.3f}" if done else "", after["adaptive"]["sf"] != sf])


if __name__ == "__main__":
    main()
