"""Link budget: how far one LoRa hop can reach, from first principles and from your own range test.

  received power (dBm) = transmit power + antenna gains - path loss
  a packet gets through while received power > receiver sensitivity + fade margin

Path loss with the log-distance model: PL(d) = PL(1 m) + 10 * n * log10(d / 1 m),
  PL(1 m) = 20*log10(4*pi/wavelength) = 25.2 dB at 433.5 MHz,
  n = 2 in free space, about 2.7-3.5 between buildings and trees, fitted below from your measurements.

  python electronics/link_budget.py      writes figures/link_budget.png and prints the range per SF

Put your range-test readings in electronics/range_test.csv (distance_m, rssi_dbm): with two or more different
distances the script fits YOUR exponent n and predicts the range from it. While that file is empty it uses a
SIMULATED example, labelled as such on the figure and in the printout: it shows the method, it is not a
measurement, and must not be presented as one.
"""
import csv, math, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
FIG = os.path.join(HERE, "figures")
FREQ_HZ = 433.5e6
TX_DBM = 8            # LORA_TX_DBM in config.h
ANT_GAIN_DBI = 0      # each spring antenna, assumed; measure with a VNA to do better
FADE_MARGIN_DB = 10   # room for fading, bodies, rain
SENSITIVITY = {7: -123, 8: -126, 9: -129, 10: -132}  # dBm, SX1276/77/78 datasheet, 125 kHz bandwidth


def fspl_db(d_m, f_hz=FREQ_HZ):
    """Free-space path loss in dB."""
    return 20 * math.log10(4 * math.pi * d_m * f_hz / 299_792_458)


PL0 = fspl_db(1.0)


def range_m(sf, n):
    """Longest distance at which a hop still has the fade margin, for path-loss exponent n."""
    max_loss = TX_DBM + 2 * ANT_GAIN_DBI - SENSITIVITY[sf] - FADE_MARGIN_DB
    return 10 ** ((max_loss - PL0) / (10 * n))


def fit_exponent(points):
    """Least-squares n from (distance_m, rssi_dbm) pairs; None without two different distances."""
    d = np.array([p[0] for p in points])
    if len(set(d)) < 2:
        return None
    loss = TX_DBM + 2 * ANT_GAIN_DBI - np.array([p[1] for p in points])
    x = 10 * np.log10(d)
    return float(np.sum(x * (loss - PL0)) / np.sum(x * x))


def simulated_example():
    """NOT MEASURED. What a site with path-loss exponent 3.1 and 6 dB of random shadowing (walls, trees, people)
    would give at these distances. It only shows how the fit works."""
    rng = np.random.default_rng(7)
    d = np.array([10, 25, 50, 100, 150, 200, 300, 450, 600, 800], dtype=float)
    rssi = TX_DBM + 2 * ANT_GAIN_DBI - (PL0 + 31 * np.log10(d)) + rng.normal(0, 6, d.size)
    return [(float(x), float(round(y))) for x, y in zip(d, rssi)]


def read_points(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return [(float(r["distance_m"]), float(r["rssi_dbm"])) for r in csv.DictReader(f)
                if r.get("distance_m") and r.get("rssi_dbm") and not r["distance_m"].startswith("#")]


def main():
    os.makedirs(FIG, exist_ok=True)
    points = read_points(os.path.join(HERE, "range_test.csv"))
    simulated = not points
    if simulated:
        points = simulated_example()
    source = "SIMULATED example, not measured" if simulated else "your range test"
    n_fit = fit_exponent(points)
    d = np.logspace(0, 4.3, 300)
    fig, a = plt.subplots(figsize=(8.5, 5.2))
    models = [(2.0, "free space (n = 2)", ":"), (2.7, "open ground, n = 2.7", "--"), (3.5, "buildings, n = 3.5", "-.")]
    if n_fit:
        models.append((n_fit, f"fitted to {source}, n = {n_fit:.2f}", "-"))
    for n, label, style in models:
        a.semilogx(d, TX_DBM + 2 * ANT_GAIN_DBI - (PL0 + 10 * n * np.log10(d)), style, color="#2a78d6" if n != n_fit else "#0b0b0b", label=label)
    for sf, s in SENSITIVITY.items():
        a.axhline(s + FADE_MARGIN_DB, color="#d03b3b", linewidth=0.8, alpha=0.4 + 0.15 * (sf - 7))
        a.text(1.3 * 5 ** (sf - 7), s + FADE_MARGIN_DB + 0.8, f"SF{sf} limit", fontsize=8, color="#d03b3b")
    if points:
        a.semilogx([p[0] for p in points], [p[1] for p in points], "o", color="#e0a000",
                   label="SIMULATED readings (not measured)" if simulated else "measured RSSI (range test)")
    a.set_ylim(-140, -10)
    a.set_xlabel("distance (m)  -  red lines: receiver sensitivity + fade margin; a hop works above its line")
    a.set_ylabel("received power (dBm)")
    a.set_title(f"433.5 MHz link budget: {TX_DBM} dBm, {ANT_GAIN_DBI} dBi antennas, {FADE_MARGIN_DB} dB fade margin"
                + ("\nreadings are a SIMULATED EXAMPLE, not measurements" if simulated else ""),
                color="#d03b3b" if simulated else "black")
    a.grid(True, which="both", alpha=0.3)
    a.legend(fontsize=8, loc="upper right")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "link_budget.png"), dpi=130)

    print(f"path loss at 1 m: {PL0:.1f} dB")
    print("predicted range per hop (m):")
    for n, label, _ in models:
        print(f"  {label:52s}" + "  ".join(f"SF{sf} {range_m(sf, n):>9,.0f}" for sf in SENSITIVITY))
    if simulated:
        print("  NOTE: the fitted line uses a SIMULATED EXAMPLE, not measurements. Put your range-test readings in")
        print("        electronics/range_test.csv (distance_m, rssi_dbm) to fit your own site.")
    # Self-checks: the textbook free-space loss at 1 km, and the fit recovering a known exponent.
    assert abs(fspl_db(1000) - (32.44 + 20 * math.log10(433.5))) < 0.05
    fake = [(dd, TX_DBM - (PL0 + 30 * math.log10(dd))) for dd in (5, 50, 500)]
    assert abs(fit_exponent(fake) - 3.0) < 1e-6
    print("check ok; figure in", FIG)


if __name__ == "__main__":
    main()
