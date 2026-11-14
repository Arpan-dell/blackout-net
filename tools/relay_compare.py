"""Relay drone test: compare heartbeat logs taken with node B on the ground and with B on the hovering drone.

Keep A and C in the same places for both runs. Laptop on node A's Wi-Fi:
  python tools/monitor.py --csv ground.csv      B on the ground, about 10 minutes, then Ctrl+C
  python tools/monitor.py --csv air.csv         B on the hovering drone, about 10 minutes, then Ctrl+C
  python tools/relay_compare.py ground.csv air.csv
  python tools/relay_compare.py --selftest
"""
import csv, statistics, sys
from monitor import track, received_pct


def summary(lines):
    """Per node: heartbeats logged, received %, median RSSI and SNR of the last hop, share that came direct."""
    stats, rows = {}, {}
    for r in csv.DictReader(lines):
        track(stats, {"id": r["node"], "seq": int(r["seq"])})
        rows.setdefault(r["node"], []).append(r)
    return {node: {"got": len(rs), "pct": received_pct(stats[node]),
                   "rssi": statistics.median(float(r["rssi"]) for r in rs),
                   "snr": statistics.median(float(r["snr"]) for r in rs),
                   "direct": 100 * sum(r["via"] == node for r in rs) / len(rs)}
            for node, rs in sorted(rows.items())}


def selftest():
    s = summary(["received_at,node,seq,via,rssi,snr",
                 "t,B,1,B,-100,1", "t,B,2,B,-90,2", "t,B,4,B,-80,3",
                 "t,C,10,B,-95,4", "t,C,11,B,-85,6"])
    assert s["B"] == {"got": 3, "pct": 75.0, "rssi": -90.0, "snr": 2.0, "direct": 100.0}, s["B"]
    assert s["C"] == {"got": 2, "pct": 100.0, "rssi": -90.0, "snr": 5.0, "direct": 0.0}, s["C"]
    print("selftest ok")


def main():
    if sys.argv[1:] == ["--selftest"]:
        return selftest()
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    runs = {}
    for name, path in (("ground", sys.argv[1]), ("air", sys.argv[2])):
        with open(path, newline="") as f:
            runs[name] = summary(f)
    print("Heard at node A. RSSI and SNR are of the last hop; 'direct' = not relayed.\n")
    print(f"{'node':<6}{'B was':<8}{'heartbeats':>11}{'received':>10}{'RSSI':>10}{'SNR':>9}{'direct':>8}")
    for node in sorted(set(runs["ground"]) | set(runs["air"])):
        for name, s in runs.items():
            if node in s:
                x = s[node]
                print(f"{node:<6}{name:<8}{x['got']:>11}{x['pct']:>9.0f}%{x['rssi']:>6.0f} dBm"
                      f"{x['snr']:>6.1f} dB{x['direct']:>7.0f}%")


if __name__ == "__main__":
    main()
