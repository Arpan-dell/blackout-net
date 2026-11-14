"""Turn the two LTspice simulations into figures for the slides.

  python electronics/plot_ltspice.py     runs LTspice on both .cir files (if it is installed) and writes
                                         figures/filter_response.png and figures/supply_rail.png

LTspice's .raw file: a text header (UTF-16) ending in "Binary:", then one record per point. AC analysis stores
every value as a complex double; transient stores time as a double and the rest as 4-byte floats.
"""
import os, subprocess
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
FIG = os.path.join(HERE, "figures")
LTSPICE = os.path.expandvars(r"%LOCALAPPDATA%\Programs\ADI\LTspice\LTspice.exe")


def read_raw(path):
    """{variable name: numpy array}, plus 'plots' = number of .step runs."""
    blob = open(path, "rb").read()
    marker = "Binary:\n".encode("utf-16-le")
    cut = blob.find(marker)
    header = blob[:cut].decode("utf-16-le")
    lines = header.splitlines()
    n_vars = int(next(l for l in lines if l.startswith("No. Variables:")).split(":")[1])
    n_pts = int(next(l for l in lines if l.startswith("No. Points:")).split(":")[1])
    names = [l.split("\t")[2] for l in lines[lines.index("Variables:") + 1:][:n_vars]]
    data = blob[cut + len(marker):]
    if "complex" in next(l for l in lines if l.startswith("Flags:")):
        rec = np.frombuffer(data, dtype=np.complex128, count=n_pts * n_vars).reshape(n_pts, n_vars)
        out = {n: rec[:, i] for i, n in enumerate(names)}
        out[names[0]] = out[names[0]].real
    else:
        rec = np.frombuffer(data, dtype=np.dtype([("t", "<f8")] + [(f"v{i}", "<f4") for i in range(1, n_vars)]), count=n_pts)
        out = {names[0]: np.abs(rec["t"])}  # LTspice may flag points by negating the time
        out.update({n: rec[f"v{i}"].astype(float) for i, n in enumerate(names[1:], 1)})
    return out


def run(cir):
    raw = os.path.join(HERE, cir.replace(".cir", ".raw"))
    if os.path.exists(LTSPICE):
        subprocess.run([LTSPICE, "-b", os.path.join(HERE, cir)], check=True, cwd=HERE)
    return read_raw(raw)


def filter_figure():
    d = run("harmonic_filter_433.cir")
    f, vdb = d["frequency"], 20 * np.log10(np.abs(d["V(out)"]))
    fig, a = plt.subplots(figsize=(8.5, 4.8))
    a.semilogx(f / 1e6, vdb, color="#2a78d6", linewidth=2)
    marks = [(433.5, "our signal 433.5 MHz", "#1baf7a"), (867, "2nd harmonic 867 MHz", "#d03b3b"), (1300.5, "3rd harmonic 1300 MHz", "#d03b3b")]
    for mhz, label, color in marks:
        v = np.interp(mhz * 1e6, f, vdb)
        a.plot(mhz, v, "o", color=color)
        a.annotate(f"{label}\n{v:.1f} dB", (mhz, v), textcoords="offset points", xytext=(8, -26 if mhz < 500 else 8), fontsize=8, color=color)
    a.set_ylim(-70, 5)
    a.set_xlabel("frequency (MHz)")
    a.set_ylabel("gain (dB), 0 dB = no loss")
    a.set_title("5th-order Chebyshev low-pass (LTspice): passes 433.5 MHz, blocks the harmonics")
    a.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "filter_response.png"), dpi=130)
    return {m: float(np.interp(m * 1e6, f, vdb)) for m, _, _ in marks}


def supply_figure():
    d = run("supply_rail.cir")
    t, v = d["time"], d["V(rail)"]
    starts = np.r_[0, np.where(np.diff(t) < 0)[0] + 1, t.size]  # .step runs are stored one after another
    fig, a = plt.subplots(figsize=(8.5, 4.8))
    mins = []
    for (s, e), cap, color in zip(zip(starts[:-1], starts[1:]), ("0.1 µF only", "10 µF", "100 µF"), ("#d03b3b", "#1baf7a", "#2a78d6")):
        keep = t[s:e] >= 5e-3
        mins.append(float(v[s:e][keep].min()))
        a.plot(t[s:e] * 1e3, v[s:e], color=color, linewidth=1.5, label=f"{cap} at the 3.3 V pins: lowest {mins[-1]:.2f} V")
    a.axhspan(2.4, 2.8, color="#d03b3b", alpha=0.12, label="ESP brown-out (restart) zone")
    a.set_xlim(9, 12)
    a.set_ylim(2.3, 3.5)
    a.set_xlabel("time (ms)  -  LoRa transmitting from 9.5 ms, Wi-Fi burst 10 to 11 ms")
    a.set_ylabel("3.3 V rail (V)")
    a.set_title("Supply rail during a transmit burst (LTspice)")
    a.grid(True, alpha=0.3)
    a.legend(fontsize=8, loc="lower right")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "supply_rail.png"), dpi=130)
    return mins


if __name__ == "__main__":
    os.makedirs(FIG, exist_ok=True)
    gains = filter_figure()
    mins = supply_figure()
    print("filter gain (dB):", {k: round(v, 2) for k, v in gains.items()})
    print("lowest rail voltage (V):", [round(m, 2) for m in mins])
    # Self-check: the figures agree with LTspice's own .meas results (see the .log files).
    assert abs(gains[433.5] + 0.24) < 0.05 and abs(gains[867] + 25.3) < 0.3 and abs(gains[1300.5] + 45.6) < 0.3
    assert len(mins) == 3 and abs(mins[0] - 2.62) < 0.02 and abs(mins[1] - 3.19) < 0.02
    print("check ok; figures in", FIG)
