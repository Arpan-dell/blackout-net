# BLACKOUT NET firmware, phase 2: adaptive spreading factor

**Get phase 1 (`../firmware`) working first.** Phase 2 is phase 1 plus adaptive spreading factor (SF), so
when something fails here and worked in phase 1, the cause is in the adaptive part.

All three nodes must run the same phase. Phase 2 uses protocol version 4 (phase 1 uses 3), so a phase 1
node and a phase 2 node ignore each other's packets.

The control-room support (`pos` over USB, node C's `@NODES` / `@MSG` lines, the sender's
phone signal) is the same in both phases; see "Position" and "Control room" in `../firmware/README.md`.

## What phase 2 adds

- Every node measures the SNR (signal-to-noise ratio) of each neighbour it hears directly and reports it in
  its heartbeat.
- The HQ (node C) picks the fastest SF, from SF7 (fastest) to SF10 (slowest), at which every node can still
  reach the HQ with 10 dB of SNR to spare. It speeds up one step at a time after two checks agree, and slows
  down at once.
- The HQ announces a switch; the announcement is relayed like any message, and every node switches at the
  same moment, about 6–10 seconds later. All nodes must use the same SF, because an SX1278 only hears
  packets sent with its own SF.
- A node that hears nothing for 2.5 heartbeat periods assumes it missed a switch, or has just started, and
  steps through SF7–SF10 until it hears the network again. The HQ never searches; it stays put so the
  others can find it.
- If a node goes silent, the HQ steps the network slower, one step per check, up to SF10, so a node that has
  become hard to hear can be heard again.
- Waits for ACKs and gaps between messages grow and shrink with the SF's air time. Heartbeats are sent every
  30 s at SF7–SF9 and every 60 s at SF10.
- The Network tab shows the current SF, the HQ's reason for it, any switch in progress and the SNR and
  margin of each direct link. On the HQ, a button turns adaptive SF on or off.

Settings are in `include/config.h` under "adaptive spreading factor".

## What to check (in this order)

| # | Test | Pass when |
|---|---|---|
| 1 | Power all three, adaptive on | within a few minutes the HQ's log shows `ADAPT SF9 -> SF8` (on a table, the links are strong), then later SF7; every node logs `RADIO now SF…` at the same moment |
| 2 | Send messages after the switch | DELIVERED as in phase 1 |
| 3 | Move A away, or put something between A and B | the HQ slows the network down; messages still arrive |
| 4 | Switch B off for 3 minutes, then on again | the HQ steps to SF10; B and A find the network again (can take up to about 5 minutes) |
| 5 | Turn adaptive off on the HQ | every node goes back to SF9 |
| 6 | Measure: `python ../tools/adaptive_test.py fixed`, then `... adaptive` | numbers for delivery, delay and air time per message, in `adaptive_results.csv` |

For the demonstration where B is switched off on purpose, turn adaptive off first: with adaptive on, the
network may need a few minutes to find B again afterwards.

---

The rest of this file is the phase 1 guide, which applies to phase 2 unchanged. Build and flash from this
`firmware-phase2` folder instead of `firmware`.

One program for all three nodes (ESP32 DevKit V1 + Ai-Thinker Ra-02, SX1278, 433 MHz).
A phone joins node A's Wi-Fi and sends a message. It travels A → B → C by LoRa. Node A shows
DELIVERED only after node C's acknowledgement has travelled back.

| Node | Role | Wi-Fi hotspot | Page at http://192.168.4.1 |
|---|---|---|---|
| A | sender gateway | `BLACKOUT_A` | Send form, message status |
| B | relay, also takes messages | `BLACKOUT_B` | Send form, message status |
| C | HQ, also takes messages | `BLACKOUT_C` | Inbox, Acknowledge button, send form |

Every node also has a Network tab with counters, the other nodes heard and the radio log.

## Flash

1. Wire each node as in the wiring diagram. Attach the antenna before powering on.
2. Install the PlatformIO extension in VS Code and open this `firmware` folder.
3. Plug in one board at a time and upload the build for that board:

   ```
   pio run -e node_a -t upload
   pio run -e node_b -t upload
   pio run -e node_c -t upload
   ```

   If the upload stalls at "Connecting...", hold the BOOT button on the board until it starts.
4. Label each box A, B or C straight away.

Settings live in `include/config.h` (pins, radio, timing) and `platformio.ini` (node identity and
position). All nodes must be built from the same `config.h`, or they will not hear each other.

## First power-on check

Open the serial monitor (`pio device monitor`). A healthy node prints:

```
selftest ok
[     210 ms] BLACKOUT NET node A (id 1)
[     260 ms] RADIO ok: SX1278 433.5 MHz, BW 125 kHz, SF9, CR 4/7, CRC on, 8 dBm setting
```

Power a second node. Within a few seconds each one logs `NEW NODE B heard via B`. That is the
two-node ping test: both radios, both antennas and the settings are working.

## Button and LED

- **SOS button (D25):** hold for a third of a second on node A or B. It queues an SOS with the text
  "SOS button pressed" and the node's name. A second press within 5 seconds is ignored. On the HQ node the
  button does nothing.
- **LED (D2):**

  | LED | Meaning |
  |---|---|
  | fast blink | a message from this node is waiting for the HQ's acknowledgement |
  | on for 3 seconds | delivered |
  | short flick | a packet was received |
  | steady on (HQ only) | an SOS in the inbox is not acknowledged yet |
  | slow blink | the radio did not start: check the wiring |

## Prove the two hops

1. Place the nodes so A and C cannot hear each other but both hear B (a building between A and C, or
   distance). Check on A's Network tab: C must be listed as "via B", never "direct".
2. Send a message from a phone on `BLACKOUT_A`. The logs must show, with the same message id:
   - on A: `TX DATA #id`, then `RX ACK #id ... from B`, then `DELIVERED #id`
   - on B: `RX DATA #id ... from A`, `RELAY DATA #id`, `RX ACK #id ... from C`, `RELAY ACK #id`
   - on C: `RX DATA #id ... from B`, `INBOX #id`, `TX ACK #id`
3. Switch B off and send again. A must show WAITING FOR HQ and then NOT DELIVERED. It must never show
   DELIVERED. There is no second route with three nodes.
4. Switch B back on while a message is still retrying. It is delivered on a later try.

**On one table** every node hears every other, so the relay is never needed. For bench work only, set
`BENCH_BLOCK_DIRECT` to 1 in `config.h` and reflash A and C: they then ignore each other's direct
packets. This fakes the distance, so say so if you show it, and set it back to 0 for the real test.

## Priority test

With all three nodes running and a laptop on `BLACKOUT_A`:

```
python ../tools/priority_test.py
```

It queues 20 normal and 3 SOS messages with priority on, then again with priority off, and prints the
delivery count and median delay of each class. Report those numbers as measured.

## Live monitor on a laptop

```
python ../tools/monitor.py
```

To get distances on its map, set `NODE_LAT` and `NODE_LON` for each node in `platformio.ini`.

## Troubleshooting

| Symptom | Check |
|---|---|
| `RADIO FAILED code -2` | Chip not found: NSS → D21, SCK → D18, MISO → D19, MOSI → D23, RESET → D14, 3.3 V, solder joints |
| Radio ok but nothing received | DIO0 → D26; same `config.h` on every node; antenna attached; both nodes powered |
| Board resets when it transmits | 3.3 V rail dips: add the 100 nF and 10 µF capacitors at the Ra-02, or a separate 3.3 V regulator |
| Many CRC errors | Nodes too close (move them a metre apart), wrong antenna, loose antenna connector |
| Phone leaves the hotspot | Choose "stay connected" when the phone says the Wi-Fi has no internet; turn mobile data off |
| Message always "direct" | A and C hear each other: see "Prove the two hops" |
| `HOLD: airtime budget` | The node used its transmit time for the hour (10 %); it resumes by itself |
| Phase 2: a node logs `RADIO now SF… searching for the network` again and again | It cannot hear anyone on any SF: check that it runs phase 2 too, then its antenna and distance |
| Phase 2: nodes on different SFs for a long time | Wait up to 5 minutes, or turn adaptive off on the HQ and restart all nodes (they all start on SF9) |
| Phase 2: `SF… FAILED code` | The radio refused the change; note the code and use phase 1 |

## Limits to state honestly

- Messages and the inbox are kept in memory only. A node that loses power forgets them.
- Transmit power is set to 8 dBm at the module. Nobody has measured the radiated power, so this is not a
  claim of compliance with the Indian 433 MHz rules.
- Message text and landmark share 37 bytes. Hindi and other non-Latin text uses about 3 bytes a character.
- Packets are not encrypted or signed. Anyone with a matching radio can read or forge them.
- The hotspot is open and takes up to 8 phones at a time.
