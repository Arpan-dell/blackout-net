# BLACKOUT NET: measured results

Real measurements on the three nodes (A: ESP32, B: NodeMCU ESP8266, C: ESP32, Ra-02 radios at 8 dBm), taken
15 November 2026 with the scripts in `tools/`. Raw output exactly as printed. Note the distances and antennas
next to each run when you repeat it.

## 1. SOS priority against plain first-in-first-out (`tools/priority_test.py`)

20 normal messages queued, then 3 SOS, on node A; delivered to the HQ (node C).

```
priority ON
  SOS    3 of 3 delivered, median delay 4.9 s
  NORMAL 20 of 20 delivered, median delay 31.2 s
priority OFF (FIFO)
  SOS    3 of 3 delivered, median delay 47.3 s
  NORMAL 20 of 20 delivered, median delay 22.3 s
```

What it shows:
- With priority on, an SOS reaches the HQ in **4.9 s** instead of **47.3 s**: about **10× faster**, 42 s sooner.
- The price: normal messages wait 8.9 s longer (31.2 s against 22.3 s), and none is lost.
- **46 of 46** messages delivered across both runs.

## 2. Adaptive spreading factor against fixed SF9 (`tools/adaptive_test.py`, phase 2)

20 normal messages from node A, nodes not moved between runs.

```
fixed: sending 20 messages from node A on SF9
fixed: SF9, 19 of 20 delivered in 129 s, median delay 80.4 s, node A air time 0.80 s per delivered message

adaptive: SF8, 20 of 20 delivered in 79 s, median delay 47.6 s, node A air time 0.34 s per delivered message
WARNING: the SF changed during the run (SF8 -> SF7). Do not use this run.
```

- **Fixed SF9 is valid:** 19 of 20 delivered, 0.80 s of air time per delivered message.
- **The adaptive run is NOT valid yet:** the HQ switched SF8 to SF7 in the middle of it. It only hints at the
  gain (all 20 delivered, 40 % sooner, 58 % less air time). **Repeat it** after the network has settled on its
  speed (node A's Network tab shows the SF, with no switch pending), and use that run on the slide.

## Still to measure

- Adaptive run, repeated (above).
- Range per hop, outdoors: distance and RSSI into `electronics/range_test.csv`.
- Battery life on a power bank.
