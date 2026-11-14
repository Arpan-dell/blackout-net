"""LoRa chirp spread spectrum: how the Ra-02 decodes packets that are weaker than the noise.

A LoRa symbol is a chirp: a tone sweeping across the whole 125 kHz band. The data (SF bits per symbol) sets
where in the band the sweep starts. The receiver multiplies by a reference down-chirp ("de-chirping"): the
sweep collapses to one steady tone, and an FFT finds it as a single tall peak. Noise is spread over all 2^SF
FFT bins, the symbol's energy lands in one, so the peak stands out even at negative SNR. That is the
"processing gain": 10*log10(2^SF) dB, about 2.5 dB more for each SF step.

  python electronics/lora_chirps.py        writes figures/lora_spectrogram.png and figures/lora_ser.png

The simulated thresholds are checked against the SX1278 datasheet decoding limits that the firmware uses
(snrFloor: -7.5 dB at SF7 ... -15 dB at SF10).
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
FIG = os.path.join(HERE, "figures")
DATASHEET_LIMIT = {7: -7.5, 8: -10.0, 9: -12.5, 10: -15.0}  # dB, same as snrFloor() in the phase 2 firmware


def chirp(sf, symbol):
    """One LoRa symbol, sampled once per chip (sample rate = bandwidth)."""
    n_chips = 2 ** sf
    n = np.arange(n_chips)
    return np.exp(2j * np.pi * (n * n / (2 * n_chips) + (symbol / n_chips - 0.5) * n))


def symbol_error_rate(sf, snr_db, symbols=4000, rng=np.random.default_rng(1)):
    """Send random symbols through white noise at this SNR, de-chirp, FFT, pick the tallest bin."""
    n_chips = 2 ** sf
    sent = rng.integers(0, n_chips, symbols)
    n = np.arange(n_chips)
    base = np.exp(2j * np.pi * (n * n / (2 * n_chips) - 0.5 * n))
    tx = base[None, :] * np.exp(2j * np.pi * sent[:, None] * n[None, :] / n_chips)
    noise_power = 10 ** (-snr_db / 10)  # signal power is 1
    noise = np.sqrt(noise_power / 2) * (rng.standard_normal(tx.shape) + 1j * rng.standard_normal(tx.shape))
    dechirped = (tx + noise) * np.conj(base)[None, :]
    received = np.argmax(np.abs(np.fft.fft(dechirped, axis=1)), axis=1)
    return np.mean(received != sent)


def snr_for_ser(sf, target=0.01, snrs=None):
    """Lowest SNR (dB) at which the symbol error rate falls to the target, by interpolating the curve."""
    snrs = np.arange(-24, -2, 0.5) if snrs is None else snrs
    ser = np.array([symbol_error_rate(sf, s) for s in snrs])
    i = np.argmax(ser <= target)
    return np.interp(np.log10(target), np.log10(np.clip(ser[[i, i - 1]], 1e-5, 1)), snrs[[i, i - 1]]), snrs, ser


def main():
    os.makedirs(FIG, exist_ok=True)
    # 1. What the chirps look like: spectrogram of four SF7 symbols, clean and buried in noise at -10 dB SNR
    sf, data = 7, [0, 32, 64, 100]
    sig = np.concatenate([chirp(sf, s) for s in data])
    rng = np.random.default_rng(2)
    noisy = sig + np.sqrt(10 ** 1.0 / 2) * (rng.standard_normal(sig.size) + 1j * rng.standard_normal(sig.size))
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.2))
    for a, x, title in ((ax[0], sig, "Four SF7 symbols, no noise"), (ax[1], noisy, "The same at SNR -10 dB")):
        a.specgram(x, NFFT=32, Fs=125e3, noverlap=28, cmap="viridis", sides="twosided")
        a.set_title(title)
        a.set_xlabel("time (s)")
        a.set_ylabel("frequency offset (Hz)")
    sym = noisy[2 * 128:3 * 128] * np.conj(chirp(sf, 0))
    a = ax[2]
    a.plot(np.abs(np.fft.fft(sym)), color="#2a78d6", linewidth=1.5)
    a.set_title("Symbol 3 de-chirped + FFT: peak at bin 64")
    a.set_xlabel("FFT bin = decoded symbol value")
    a.set_ylabel("magnitude")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "lora_spectrogram.png"), dpi=130)

    # 2. Symbol error rate against SNR for SF7..SF10, with the datasheet limits marked
    fig, a = plt.subplots(figsize=(8, 5))
    colors = {7: "#2a78d6", 8: "#1baf7a", 9: "#e0a000", 10: "#d03b3b"}
    thresholds = {}
    for sf in (7, 8, 9, 10):
        thr, snrs, ser = snr_for_ser(sf)
        thresholds[sf] = thr
        a.semilogy(snrs, np.clip(ser, 1e-4, 1), "o-", color=colors[sf], markersize=3, label=f"SF{sf}: 1 % errors at {thr:.1f} dB")
        a.axvline(DATASHEET_LIMIT[sf], color=colors[sf], linestyle=":", linewidth=1)
    a.set_ylim(1e-4, 1)
    a.set_xlabel("SNR per chip (dB)  -  dotted lines: SX1278 datasheet decoding limits")
    a.set_ylabel("symbol error rate")
    a.set_title("LoRa decodes below the noise floor: each SF step gains about 2.5-3 dB")
    a.grid(True, which="both", alpha=0.3)
    a.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "lora_ser.png"), dpi=130)

    print("SNR for 1 % symbol errors (uncoded):", {sf: round(t, 1) for sf, t in thresholds.items()})
    print("SX1278 datasheet limits            :", DATASHEET_LIMIT)
    steps = np.diff([thresholds[s] for s in (7, 8, 9, 10)])
    # Self-check: each SF step must buy close to the 3 dB of processing gain theory gives.
    assert all(-3.6 < d < -2.2 for d in steps), steps
    # Self-check: the decoder works well below 0 dB SNR, near the datasheet limits (which include coding gain).
    assert all(t < 0 and abs(t - DATASHEET_LIMIT[sf]) < 4 for sf, t in thresholds.items()), thresholds
    print("check ok; figures in", FIG)


if __name__ == "__main__":
    main()
