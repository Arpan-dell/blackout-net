# BLACKOUT NET: the electronics behind it

Six pieces that show what happens to a packet inside the hardware, each one runnable and checked:

| File | Tool | What it shows | Key result |
|---|---|---|---|
| `lora_chirps.py` | Python | How LoRa chirps let the Ra-02 decode signals *below* the noise | SF9 decodes at about −14 dB SNR; each SF step gains about 2.7 dB |
| `relay_regeneration.py` | Python | Why our relay rebuilds each packet instead of amplifying it | 3 hops at −13.5 dB each: 60 % delivered (ours) against 0 % (amplifier relay) |
| `link_budget.py` + `range_test.csv` | Python | How far one hop reaches, from physics and from our range test | SF9 with buildings (n = 3.5): about 800 m per hop. Until `range_test.csv` has your readings, the fitted line uses a **simulated example, labelled as such**: never present it as measured |
| `snr_filter.py` | Python | The digital filter in our firmware that smooths link quality | noise down to 0.42×, follows a real change in 7 heartbeats |
| `harmonic_filter_433.cir` | LTspice | A 433 MHz filter that keeps our transmitter out of other bands | 0.24 dB loss at 433.5 MHz, −25 dB at 867 MHz, −46 dB at 1300 MHz |
| `supply_rail.cir` | LTspice | Why a node restarted during transmit, and why the capacitor fixes it | 3.3 V rail dips to 2.62 V with 0.1 µF only, 3.19 V with 10 µF |
| `plot_ltspice.py` | Python | Runs both LTspice circuits and draws them for the slides | `filter_response.png`, `supply_rail.png` |

Run each Python file with `python electronics/<file>`: it prints its numbers, checks them against theory, and
writes a figure to `electronics/figures/`. Open each `.cir` file in LTspice and press Run to see the plot; the
`.meas` results appear under View → SPICE Error Log.

## 1. What happens to a packet at a relay ("reviving" it)

Node B does not amplify the weak signal it receives. Inside the SX1278 the signal goes through:

```
antenna → LNA (low-noise amplifier) → mixer (433.5 MHz down to a low IF) → IF filter (125 kHz)
        → ADC → de-chirping + FFT (LoRa demodulation) → error correction (CR 4/7) → CRC check → bits
```

The firmware then checks the packet (version, length, node ids, duplicate filter, hop count) and builds a
**brand-new** packet that the SX1278 transmits at full power. This is **decode-and-forward**: every relay
restores the packet to its original strength and removes all the noise it picked up on the way. An
amplifying relay would boost the noise too, and every hop would add more (`relay_regeneration.py`).

The transmit power is set at 8 dBm on purpose: India's licence-free 433 MHz band allows 10 mW ERP, so a
relay must not "boost" beyond that. More range comes from a slower SF (more processing gain), better
antennas, height (the relay drone), and filtering, not from raising power.

## 2. LoRa chirp spread spectrum (`lora_chirps.py`)

Each LoRa symbol is a chirp sweeping across the whole 125 kHz band; the data sets where the sweep starts.
The receiver multiplies by a reference down-chirp, which turns the sweep into one steady tone, and an FFT
finds it as one tall peak (figure `lora_spectrogram.png`: invisible in the noise at −10 dB, obvious after
de-chirping). The symbol's energy lands in one FFT bin while the noise spreads over all 2^SF bins: this
**processing gain** is 10·log10(2^SF) dB, about 3 dB per SF step. `lora_ser.png` shows it, next to the
SX1278 datasheet limits that the phase 2 firmware uses to choose its SF.

## 3. Link budget (`link_budget.py`)

`received power = 8 dBm + antenna gains − path loss`, and a hop works while that stays above the receiver
sensitivity (−129 dBm at SF9) plus a 10 dB fade margin. Path loss uses the log-distance model with the
free-space value at 1 m (25.2 dB at 433.5 MHz). **Fill in `range_test.csv` with your range test**
(distance in metres, RSSI from the control room) and the script fits your site's exponent *n* and predicts
the range per SF from it. Put that range into the control room (`--range`) so its drone plan uses it.

## 4. The firmware's digital filter (`snr_filter.py`)

Phase 2 smooths each link's SNR with `snr = 0.7·snr + 0.3·new` (`main.cpp`): a first-order IIR low-pass,
H(z) = 0.3 / (1 − 0.7 z⁻¹). Without it, one noisy reading could make the HQ switch the whole network's SF.
The figure shows the jitter removed and the frequency response (−3 dB at 0.057 cycles per heartbeat).

## 5. Transmit harmonic filter (`harmonic_filter_433.cir`)

A transmitter also puts out weaker copies at 2× and 3× its frequency (867 MHz is in India's 865–867 MHz
band; 1300 MHz is aviation radionavigation). A 5th-order Chebyshev low-pass filter between the Ra-02 and the
antenna removes them while passing 433.5 MHz almost untouched. Values come from the normalised Chebyshev
table (0.1 dB ripple), scaled to 50 Ω and 520 MHz: 7 pF – 21 nH – 12 pF – 21 nH – 7 pF. It can be built
with 0603 RF parts on a small board between the Ra-02's antenna pad and the antenna socket.

## 6. Supply rail (`supply_rail.cir`)

A node draws sudden bursts: about 300 mA for Wi-Fi, 40 mA for LoRa. The 3.3 V regulator needs microseconds
to respond, so meanwhile the current must come from a capacitor next to the module. With only 0.1 µF the
rail dips to 2.62 V, about where the ESP restarts (brown-out); with 10 µF it stays at 3.19 V. This explains
node B's restarts during testing, and is why every Ra-02 has 10 µF + 100 nF across its supply pins.

## What to show the judges

1. **On screen:** the six figures, plus the LTspice plots (filter response, rail voltage for the three
   capacitor values). Say the result of each in one sentence.
2. **Live, if you can get the parts:**
   - an **RTL-SDR dongle** (about ₹3,000) with SDR# or SDR++ tuned to 433.5 MHz: press SOS and the chirps
     appear on the waterfall, the same picture as `lora_spectrogram.png`, but real;
   - a **NanoVNA** (about ₹4,000) on the antenna: its SWR / S11 at 433.5 MHz shows how well it is matched;
   - an **oscilloscope** on the 3.3 V pin during a transmit, with and without the 10 µF capacitor.
3. **Measured numbers from the system itself:** RSSI and SNR per node in the control room, delivery counts,
   the priority test, the adaptive-SF test (`tools/adaptive_test.py`) and your range test.

## What not to claim

- The relays do not amplify or add power; they regenerate. More power than 10 mW ERP would break the rules.
- The filter and the supply simulations are designs and models; only claim measured figures as measured.
- `range_test.csv` predictions are only as good as the readings you put in.
