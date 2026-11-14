# BLACKOUT NET firmware

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

### Or with the Arduino IDE

1. Make one sketch per node: `python tools/make_arduino_sketch.py` (add `--phase 2` for phase 2). This
   writes `arduino/blackout_node_A`, `_B` and `_C`, each with its node already set. Run it again after any
   change to the firmware.
2. Arduino IDE, once: Boards Manager → **esp32** by Espressif (2.0.17 or 3.x both build); Library Manager →
   **RadioLib 6.6.0** (not 7 or 8) and **ArduinoJson 7.2.1**.
3. File → Open → `arduino/blackout_node_A/blackout_node_A.ino`. Tools → Board → **ESP32 Dev Module** for an
   ESP32 DevKit, or **NodeMCU 1.0 (ESP-12E Module)** for a NodeMCU (ESP8266). Tools → Port → the board's COM
   port. Press **Upload** (→). Repeat with `_B` and `_C` on their boards.
4. Tools → Serial Monitor at **115200** baud shows `selftest ok`; type `pos <lat> <lon>` there to set the
   position.

If the IDE runs out of memory while compiling, `tools\upload_node.bat B COM8 8266` compiles and uploads with
one compiler at a time (leave off `8266` for an ESP32).

**Two boards work, and can be mixed:** an ESP32 DevKit (wiring above) or a NodeMCU ESP8266 (SCK D5, MISO D6,
MOSI D7, NSS D8, RESET D0, DIO0 D2, DIO1 D1, SOS button D3 to GND, LED from 3V3 through 220 Ω to D4). The
pins switch by themselves when you pick the board. On a NodeMCU the hotspot cannot measure the sender's
phone signal, so use an ESP32 for node A, the gateway phones join; B and C can be either.

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

## Coordinator PIN

The HQ inbox, everyone's messages and the settings (SOS-first switch, adaptive SF) need the coordinator PIN,
`COORD_PIN` in `include/config.h` (default `202611`: **change it**, and flash every node with the same one).
On the phone page, open the HQ inbox or Network tab and enter it once; the phone remembers it. Senders need
no PIN: each phone sees only its own messages and may have 3 on their way at a time. The test scripts in
`tools/` read the PIN from `config.h` by themselves.

## Position (for the map and for finding the sender)

- Type its latitude and longitude into the serial monitor (115200 baud, line ending "New Line"), for
  example `pos 28.749912 77.116403`. It is kept through restarts. `pos clear` removes it.
- Otherwise `NODE_LAT` / `NODE_LON` in `platformio.ini` (or in the Arduino sketch's `config.h`) are used.
- Nodes riding on drones need neither: the control room shows them at their drone's GPS position.

The node's start-up log says which one it is using.

## Control room (node C on USB)

Node C prints two extra kinds of line for `tools/control_room.py`: `@NODES {…}` every 5 seconds (the same
JSON as `/api/nodes`) and `@MSG {…}` for every message that reaches the inbox, with the sending node's
position and the sender's phone signal. Either plug node C into the control room laptop
(`python ../tools/control_room.py --serial COM5`), or into the gimbal drone's companion computer running
`../tools/hq_forward.py`. See plan.md, sections 4c and 5.8.

Protocol version: phase 1 is version 3, phase 2 is version 4. Flash all three nodes from the same folder.

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

## Limits to state honestly

- Messages and the inbox are kept in memory only. A node that loses power forgets them.
- Transmit power is set to 8 dBm at the module. Nobody has measured the radiated power, so this is not a
  claim of compliance with the Indian 433 MHz rules.
- Message text and landmark share 37 bytes. Hindi and other non-Latin text uses about 3 bytes a character.
- Packets are not encrypted or signed. Anyone with a matching radio can read or forge them.
- The hotspot is open and takes up to 8 phones at a time.
