"""The digital filter inside the phase 2 firmware: smoothing each link's SNR before the HQ picks a speed.

Every heartbeat gives one SNR reading per neighbour, and single readings jump by several dB (fading, people
walking past). The firmware smooths them with a first-order IIR low-pass filter (an exponential moving average):

    snr_avg = 0.7 * snr_avg + 0.3 * snr_new          (main.cpp, handlePacket)
    H(z) = alpha / (1 - (1 - alpha) z^-1),  alpha = 0.3

  noise left after filtering:  sqrt(alpha / (2 - alpha)) = 0.42 of the original (8 dB of noise -> 3.4 dB)
  reaction to a real change:   90 % after ln(0.1) / ln(0.7) = 6.5 heartbeats (about 3 minutes at 30 s)

  python electronics/snr_filter.py      writes figures/snr_filter.png
"""
import math, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
FIG = os.path.join(HERE, "figures")
ALPHA = 0.3


def ewma(x, alpha=ALPHA):
    y = np.empty(len(x))
    y[0] = x[0]  # the firmware starts from the first reading
    for i in range(1, len(x)):
        y[i] = (1 - alpha) * y[i - 1] + alpha * x[i]
    return y


def main():
    os.makedirs(FIG, exist_ok=True)
    rng = np.random.default_rng(3)
    true = np.where(np.arange(120) < 60, 8.0, 0.0)  # a link that gets 8 dB worse at heartbeat 60
    readings = true + rng.normal(0, 3, true.size)
    smooth = ewma(readings)

    fig, ax = plt.subplots(1, 2, figsize=(13, 4.4))
    a = ax[0]
    a.plot(readings, ".", color="#b0b0b0", label="raw SNR per heartbeat")
    a.plot(smooth, color="#2a78d6", linewidth=2, label="smoothed (alpha = 0.3)")
    a.plot(true, "--", color="#0b0b0b", linewidth=1, label="true link quality")
    a.set_xlabel("heartbeat number (one every 30 s)")
    a.set_ylabel("SNR (dB)")
    a.set_title("Smoothing removes the jitter, still follows a real change")
    a.legend(fontsize=8)
    a.grid(True, alpha=0.3)

    f = np.linspace(0.001, 0.5, 400)  # cycles per heartbeat (0.5 = Nyquist)
    z = np.exp(2j * np.pi * f)
    h = ALPHA / (1 - (1 - ALPHA) / z)
    a = ax[1]
    a.plot(f, 20 * np.log10(np.abs(h)), color="#2a78d6", linewidth=2)
    fc = f[np.argmax(20 * np.log10(np.abs(h)) <= -3)]
    a.axvline(fc, color="#d03b3b", linestyle=":", label=f"-3 dB at {fc:.3f} cycles per heartbeat")
    a.set_xlabel("frequency (cycles per heartbeat)")
    a.set_ylabel("gain (dB)")
    a.set_title("Frequency response: a first-order low-pass")
    a.legend(fontsize=8)
    a.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "snr_filter.png"), dpi=130)

    # Self-checks against the formulas: noise reduction, and 90 % step response time.
    long_noise = rng.normal(0, 1, 200_000)
    ratio = np.std(ewma(long_noise)[100:])
    assert abs(ratio - math.sqrt(ALPHA / (2 - ALPHA))) < 0.01, ratio
    step = ewma(np.r_[np.zeros(1), np.ones(20)])
    assert np.argmax(step >= 0.9) == math.ceil(math.log(0.1) / math.log(1 - ALPHA)), step
    print(f"noise left after filtering: {ratio:.2f} of the original; -3 dB corner {fc:.3f} cycles/heartbeat; "
          f"90 % of a step after {math.ceil(math.log(0.1) / math.log(1 - ALPHA))} heartbeats")
    print("check ok; figure in", FIG)


if __name__ == "__main__":
    main()
