"""Why node B "revives" a packet by decoding it, not by amplifying it.

Two ways a relay can pass a weak packet on:
  amplify-and-forward (AF): boost whatever arrives, signal AND noise, and send it on. Noise from every hop adds
      up: 1/SNR_end = 1/SNR_1 + 1/SNR_2 + ... so each hop makes the packet worse.
  decode-and-forward  (DF): demodulate to bits, check the CRC, build a brand-new packet and send it at full
      power. Noise stops at every relay; a packet only fails if one hop on its own fails.
BLACKOUT NET's relays are decode-and-forward: radio.readData() + CRC check, then transmit() of a fresh packet.

  python electronics/relay_regeneration.py      writes figures/relay_af_vs_df.png

Packet length: a full 53-byte packet at SF9, 125 kHz, CR 4/7 is 92 LoRa symbols (Semtech's formula). Delivery
is counted conservatively, without the 4/7 code's error correction: every symbol must be right.
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from lora_chirps import FIG, symbol_error_rate

SF, SYMBOLS = 9, 92


def ser_curve():
    snrs = np.arange(-24.0, -4.0, 0.5)
    ser = np.array([symbol_error_rate(SF, s, symbols=8000) for s in snrs])
    floor = 1 / (8000 * 4)  # below what the simulation can resolve
    return snrs, np.clip(ser, floor, 1)


def make_ser(snrs, ser):
    return lambda snr_db: 10 ** np.interp(snr_db, snrs, np.log10(ser))


def delivery(hops, hop_snr_db, ser):
    """Probability a packet crosses `hops` equal hops, for both relay types."""
    p_hop = (1 - ser(hop_snr_db)) ** SYMBOLS
    df = p_hop ** hops
    snr_end = 10 * np.log10(1 / (hops / 10 ** (hop_snr_db / 10)))  # AF: noise powers add up
    af = (1 - ser(snr_end)) ** SYMBOLS
    return af, df


def main():
    ser = make_ser(*ser_curve())
    hops = np.arange(1, 7)
    fig, a = plt.subplots(figsize=(8, 5))
    for hop_snr, style in ((-13.5, "-"), (-14.5, "--")):
        af, df = np.array([delivery(h, hop_snr, ser) for h in hops]).T
        a.plot(hops, 100 * df, "o" + style, color="#1baf7a", label=f"decode-and-forward (ours), each hop at {hop_snr} dB SNR")
        a.plot(hops, 100 * af, "s" + style, color="#d03b3b", label=f"amplify-and-forward, each hop at {hop_snr} dB SNR")
    a.set_xlabel("number of hops (node A to the HQ)")
    a.set_ylabel("packets delivered (%)")
    a.set_ylim(-3, 103)
    a.set_title("SF9: regenerating at every relay keeps long chains working")
    a.grid(True, alpha=0.3)
    a.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "relay_af_vs_df.png"), dpi=130)

    af1, df1 = delivery(1, -13.5, ser)
    af3, df3 = delivery(3, -13.5, ser)
    print(f"each hop at -13.5 dB SNR, SF9: 1 hop  AF {100*af1:5.1f} %  DF {100*df1:5.1f} %")
    print(f"                                3 hops AF {100*af3:5.1f} %  DF {100*df3:5.1f} %")
    assert abs(af1 - df1) < 1e-9                      # one hop: no relay, both the same
    assert df3 > af3 + 0.3                            # three hops: regeneration clearly wins
    print("check ok; figure in", FIG)


if __name__ == "__main__":
    main()
