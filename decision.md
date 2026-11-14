# BLACKOUT NET: decisions

Each entry gives what was chosen, what else was considered, and why. The procedure is in
[plan.md](plan.md).

## Hardware

### Radio: Ai-Thinker Ra-02 (SX1278, 433 MHz)
- **Instead of:** HopeRF RFM96W (the earlier plan), 868/915 MHz modules, SX1262 modules.
- **Why:** the team selected it and can buy it locally from Robu.in. 433.05–434.79 MHz has a licence-exempt
  class for low-power devices in India, and the module has an I-PEX antenna socket, so no RF track has to be
  soldered.
- **Cost:** it is a small surface-mount module, so it needs a breakout board, and its pads differ from the
  RFM96W's. All three nodes must use the identical module.

### Same wiring on every node
- **Instead of:** a separate pin map per role.
- **Why:** any board can become any node, and a spare can replace a broken one in minutes.

### Two boards supported: ESP32 DevKit and NodeMCU ESP8266 (added 15 November 2026)
- **Instead of:** ESP32 only.
- **Why:** node B is a NodeMCU (ESP8266); nodes A and C are ESP32-WROOM DevKits. One program serves both; the pins, storage and
  library differences switch by themselves when the board is chosen in the Arduino IDE. The radio protocol
  is the same, so ESP32 and ESP8266 nodes work together.
- **Cost:** an ESP8266 hotspot cannot measure a phone's signal, so the sender's search circle needs node A
  on an ESP32. The ESP8266 has 80 KB of RAM: 44 KB is used before the hotspot starts. Phase 2 has the same
  changes but has only been compiled for the ESP32.

### Power: wall charger plus a power bank for the demonstration
- **Instead of:** wall charger only.
- **Why:** the team chose wall chargers for convenience. A project named BLACKOUT NET will be asked what
  happens in a blackout, so the demonstration still runs on power banks.

### Position typed in once over USB; nodes on drones take the drone's GPS
- **Instead of:** a GPS module on every node (the team decided against it), or only `platformio.ini`.
- **Why:** node A stays put, so typing its position once (`pos lat lon` in the serial monitor, kept in
  flash) is enough, without reflashing. Nodes B and C ride on drones that already have GPS: the control room
  shows them at their drone's live position from the GCS. No extra part, wire or library.
- **Why USB and not the phone page:** the hotspot is open; anyone could move a node on the map and send the
  scout to the wrong place. USB needs the box in hand.
- **Cost:** a ground node that is moved keeps its old position until it is typed again.

## Firmware structure

### PlatformIO with pinned versions
- **Instead of:** Arduino IDE.
- **Why:** platform, RadioLib and ArduinoJson versions are fixed in `platformio.ini`, so every teammate builds
  exactly the same thing, and one command builds and flashes each role.

### RadioLib
- **Instead of:** the Arduino "LoRa" library by Sandeep Mistry.
- **Why:** it has a direct SX1278 class, reports clear error codes, computes time on air (needed for the
  airtime budget) and gives RSSI and SNR per packet.

### One program, node identity chosen at build time
- **Instead of:** three separate programs.
- **Why:** one bug fix reaches every node, and nodes cannot drift apart in radio settings or packet format,
  which would stop them hearing each other.

### Web page stored inside the firmware
- **Instead of:** a file in the ESP32's LittleFS storage.
- **Why:** a LittleFS page needs a second upload step, and forgetting it gives a blank page on demo day.
  Built in, one flash does everything.
- **Cost:** changing the page means reflashing.

### ESP32's built-in WebServer and DNSServer
- **Instead of:** ESPAsyncWebServer.
- **Why:** they ship with the ESP32 core, so there is no extra library to install or keep compatible. A
  handful of phones polling every 1.5 s is well within what they can handle.

### Phones poll every 1.5 seconds
- **Instead of:** WebSockets or Server-Sent Events.
- **Why:** simplest thing that keeps the status current, and it recovers by itself when a phone drops off
  the Wi-Fi and comes back.

### Messages kept in memory
- **Instead of:** saving them in flash (NVS or LittleFS).
- **Why:** time. It is a known limit, listed in plan.md, and the first upgrade if time allows.

## Protocol

### Compact binary packets
- **Instead of:** JSON over the radio.
- **Why:** at SF9 every byte costs air time, and air time is capped at 10 % per hour. The header is 13 bytes;
  the same fields in JSON would be about 100.

### A "last hop" byte in every packet
- **Instead of:** the original packet layout, which had no such field.
- **Why:** without it node C cannot tell whether a message came from A directly or through B, and proving
  the relay is the core of the demonstration.

### Try number in the duplicate filter
- **Instead of:** filtering on origin and message id only.
- **Why:** a retry has to be relayed again. Filtering on the id alone made the relay throw away every retry.

### Random starting message id at boot
- **Instead of:** counting from 0 after every reboot, or saving the counter in flash.
- **Why:** after a reboot, ids starting at 0 would match ids the relay still remembers, and new messages
  would be dropped as duplicates. A random start avoids this without writing to flash.

### Delivery confirmed end to end by C only
- **Instead of:** each hop confirming to the previous one, or "sent" counting as delivered.
- **Why:** only C storing the message means the coordinators can see it. A finished transmission says
  nothing about whether anyone received it.

### Relay by controlled flooding (TTL, duplicate filter, random wait)
- **Instead of:** fixed routes or a routing table.
- **Why:** simplest scheme that works, and it needs no change if a fourth node is added: a second path then
  appears by itself. The random wait of 0.1–0.4 s keeps two relays from transmitting at the same instant.

### Listen before talk
- **Instead of:** transmitting whenever something is queued.
- **Why:** a node waits while the radio detects someone else's packet, which reduces collisions between A's
  retries and B's relaying. It gives up waiting after 1.5 s so a stuck reading cannot silence a node.

### Retries: 5 tries, wait growing each time, plus a random part
- **Instead of:** unlimited retries or a fixed wait.
- **Why:** bounded air time, a clear end state (EXPIRED) for the sender, and less chance that two senders
  keep colliding.

### Relayed packets and ACKs go before a node's own messages
- **Instead of:** one queue for everything.
- **Why:** a message that has already travelled part of the way is closer to being delivered, and an ACK
  ends a sender's retries, which saves air time.

### SOS before normal, switchable to plain FIFO
- **Instead of:** priority always on.
- **Why:** the comparison against plain FIFO has to be measured on the same radios with the same messages.
  The switch on the Network tab and `tools/priority_test.py` make that possible.

### Heartbeat every 30 seconds
- **Instead of:** every 10 seconds.
- **Why:** each heartbeat is about 0.17 s on air and B relays the others', so B sends three per period. At
  30 s that is about 2 % of air time; at 10 s about 5 %, half of the 10 % limit gone before any real message.
- **Cost:** a dead node is reported after 90 s instead of 30 s.

### Text limit counted in bytes (37 for message plus landmark)
- **Instead of:** a character limit.
- **Why:** the packet limit is in bytes. Hindi and other non-Latin scripts take about 3 bytes a character,
  so a character limit would let messages through that do not fit.

## Radio settings

### 433.5 MHz, SF9, 125 kHz, coding rate 4/7, CRC on
- **Instead of:** faster settings (SF7) or longer range settings (SF11–12).
- **Why:** the starting profile from the project handoff. SF9 is a middle ground between range and air
  time (about 0.4 s for a full packet).

### Transmit power set to 8 dBm
- **Instead of:** the module's maximum of about 18 dBm.
- **Why:** the Indian exemption class allows 10 mW ERP (about 10 dBm). With a small antenna gain, 8 dBm at
  the module leaves margin. This is not a claim of compliance: radiated power still has to be measured.

### Air time capped at 10 % in any hour
- **Instead of:** no limit.
- **Why:** the 10 % duty cycle is part of the same exemption class. The firmware tracks its own air time
  and holds transmissions once the hour's 360 s are used.

## Wi-Fi and phone page

### Every node has a hotspot, and a phone can send through any of them (changed 15 November 2026)
- **Instead of:** B as a radio-only relay and C as receive-only (the first plan).
- **Why:** the team asked for it: whoever is near any node can send an SOS. A message sent through B goes to
  C by radio like one from A. One sent through C, the HQ, goes straight into its inbox and shows DELIVERED at
  once; C's SOS button works the same way.
- **Cost:** B's hotspot uses memory and power; anyone joining `BLACKOUT_C` can also open the HQ inbox tab.

### Open hotspot, captive portal
- **Instead of:** a password-protected network.
- **Why:** anyone nearby must be able to ask for help without being told a password. The captive portal
  opens the page by itself when a phone joins.
- **Cost:** anyone in range can send requests. The firmware limits the queue, and the button has a 5 s
  lock, but there is no per-person limit yet.

### A, B and C on different Wi-Fi channels (1, 11 and 6)
- **Why:** less interference between the three hotspots when the nodes are tested side by side.

### Separate "Acknowledge" for the coordinator
- **Instead of:** using the radio ACK as the coordinator's reply.
- **Why:** "delivered to HQ" and "a person at HQ has seen it" are different facts, and the handoff requires
  them to be kept apart.

### SOS button: hold 0.3 s, 5 s lock, ignored on the HQ node
- **Why:** the hold filters switch bounce and knocks on the box; the lock stops a stuck or repeatedly pressed
  button from flooding the channel; the HQ is the receiver, so an SOS from it has nowhere to go.

### Coordinator PIN, not a Wi-Fi password on the HQ (added 15 November 2026)
- **Instead of:** a WPA2 password on `BLACKOUT_C` (the first audit's suggestion).
- **Why:** anyone must be able to send an SOS through C, so its hotspot stays open. What needs protecting is
  the HQ's power: reading the inbox, acknowledging tickets, and changing settings (`/api/mode`). Those now need
  `COORD_PIN` from `config.h`, sent as `?pin=`; the phone page asks for it once. After 5 wrong tries the PIN
  is refused for 30 s, so it cannot be guessed quickly.
- **Cost:** someone guessing can lock coordinators out for 30 s at a time. The PIN travels unencrypted over
  the open Wi-Fi, so a determined attacker nearby could still capture it.

### Each phone sees only its own messages, at most 3 on their way at once
- **Why:** before, anyone on the hotspot could read every sender's text and landmark at `/api/messages`, and
  one phone could fill the 32-message queue so nobody else could send an SOS. Each message now remembers the
  phone's address; a phone sees only its own, and may have 3 unfinished at a time. Message text is also left
  out of the radio log on the Network tab. The test scripts send the PIN, which lifts the limit.
- **Cost:** a phone that rejoins and gets a new address loses sight of its earlier messages.

### An unanswered SOS is never overwritten in the HQ inbox
- **Why:** when the 32 slots were full, the oldest message was reused even if it was an unanswered SOS, and
  its sender still saw DELIVERED. Now the oldest acknowledged message goes first, then the oldest unanswered
  normal one. If all 32 are unanswered SOS, the new message is not kept and not confirmed, so its sender
  retries and ends on NOT DELIVERED, which is the truth. Checked at every start by the self-test.

## Laptop tools

### Browser dashboard served by a Python script
- **Instead of:** the first version's tkinter window, or reading the boards over USB serial.
- **Why:** Python's standard library only, so nothing to install. A browser page could show the map,
  charts and alerts that tkinter could not show well. Polling over Wi-Fi needs no cable to the node, and the
  same `/api/nodes` data feeds the phone page.

### The map shows routes the nodes actually use, not routes chosen by distance
- **Instead of:** picking routes from GPS distance.
- **Why:** walls and terrain matter more than metres, so measured signal strength is a better guide than
  distance. Routing belongs in the firmware, and flooding already finds every path that works.

## Phase 2: adaptive spreading factor

### Phases in separate folders
- **Instead of:** adding the feature to the one firmware folder, or keeping it on a git branch.
- **Why:** phase 1 can be proven on the hardware first. A fault that appears only with phase 2 is then in
  the adaptive part. Two folders are easier for the whole team to find than a branch.
- **Cost:** a fix to the shared parts must be made in both folders.
- **Control-room support went into both phases** (at the team's request), not a third folder: whichever
  phase is flashed works with the control room. Phase 1 now uses protocol version 3 and phase 2 version 4,
  so boards with old and new firmware ignore each other instead of misreading the new message layout.

### One SF for the whole network, chosen by the HQ
- **Instead of:** a different SF for each link, as the brief suggested ("a distant node slower, a nearby
  node faster").
- **Why:** an SX1278 receives only packets sent with the SF it is set to, and the relay forwards by
  broadcast to whoever hears it. A per-link SF would need each node to listen on several SFs at once (the
  multi-channel gateway chips used by LoRaWAN do this; the SX1278 cannot) or a time schedule with clock
  synchronisation. One shared SF avoids both. The network is set by its weakest needed link, and in a
  three-node line every link is needed anyway.
- **Cost:** one weak link slows every link.

### HQ is the coordinator
- **Instead of:** every node deciding for itself.
- **Why:** one decision-maker means nodes never disagree about the SF. The HQ already receives everyone's
  heartbeats.

### Decision from SNR with a 10 dB margin
- **Instead of:** RSSI, or delivery statistics.
- **Why:** SNR decides whether LoRa can decode, and the SX1278's decoding limit per SF is in its datasheet
  (−7.5 dB at SF7 down to −15 dB at SF10). SNR in the same bandwidth stays about the same when the SF
  changes, so one measurement predicts every SF. 10 dB is the usual LoRa safety margin for fading and
  movement.

### Only SF7 to SF10
- **Instead of:** SF7 to SF12.
- **Why:** at SF11 and SF12 a full packet takes about 1.7 s and 3.2 s on air, heartbeats alone would eat
  much of the 10 % air time allowance, and a node searching for the network would take much longer.

### "Fastest SF that still connects everyone", not "fastest SF for the worst link"
- **Why:** a weak link that is not needed (for example A to C directly, when both reach B well) must not
  hold the network back. The HQ checks which nodes remain reachable, through relays, at each SF.

### Slow down at once, speed up one step after two checks agree
- **Why:** a wrong step faster loses messages; a wrong step slower only costs time. The two-check rule
  stops the network flipping back and forth on noisy measurements.

### A silent node makes the HQ step slower
- **Why:** the node may have dropped out because the current SF is too fast for its link. Stepping slower
  is the only way to hear it again. It is no longer waited for after 10 minutes.

### Switch announced ahead, with the time left, sent twice
- **Instead of:** switching as soon as the announcement arrives.
- **Why:** the announcement has to be relayed before anyone switches, or the nodes further away never hear
  it. Each relay rewrites "time left" as it transmits, and each receiver subtracts the packet's air time, so
  all nodes switch within a fraction of a second of each other. Two copies protect against one lost packet.

### A lost node searches through the SFs; the HQ never does
- **Instead of:** a fixed "meeting" SF that everyone returns to on a schedule.
- **Why:** it needs no shared clock and also handles newly started nodes. The HQ stays put so there is
  something fixed to find.
- **Cost:** finding the network again can take up to about 5 minutes.
- **Fixed 15 November 2026:** "lost" first meant "heard nothing at all". On the real boards A and B restarted
  together, came back on the default SF9 while the HQ was on SF7, heard each other, and so never searched.
  Now only packets that came from the HQ (directly or relayed) count.

### Heartbeat every 60 s at SF10
- **Why:** a heartbeat at SF10 takes about twice the air time of one at SF9; doubling the interval keeps
  heartbeats at the same share of the 10 % allowance.

### Waits follow the air time
- **Instead of:** fixed waits tuned for SF9.
- **Why:** at SF10 a fixed 6 s ACK wait is too short and causes needless retries; at SF7 it wastes time.

### Adaptive SF can be switched off on the HQ
- **Why:** the gain has to be measured against the fixed setting on the same radios in the same places
  (`tools/adaptive_test.py`). Off is also the safer setting for the relay-failure demonstration.

## Drones and control room

### Node B on a relay drone, node C (the HQ) on the gimbal drone
- **Instead of:** the swarm's own task (spot an enemy drone, send interceptors), or C on the ground at the
  control room.
- **Why:** this is the team's plan. B in the air makes the hops longer: buildings, trees and the ground limit
  LoRa range more than anything else. C on the gimbal drone S-01 puts the HQ, the camera and the drone that
  goes to look in one place.
- **Cost:** while S-01 is switched off there is no HQ, so messages expire. Keeping C on the ground at the
  control room (on the laptop's USB) avoids that and needs no forwarder; the control room supports both
  (`--serial` or `--udp`).

### Both nodes powered from the drones' 5 V outputs
- **Instead of:** their own power banks.
- **Why:** the drones have 5 V outputs, and a power bank adds weight.
- **Cost:** a battery change restarts the node. The control room shows the restart and keeps every message.

### Node C's output reaches the control room through S-01's companion computer
- **Instead of:** the laptop joining `BLACKOUT_C`, or node C joining the drones' router as a Wi-Fi client.
- **Why:** the companion computer is already on the drones' Wi-Fi, so a 40-line forwarder
  (`tools/hq_forward.py`) is enough. The laptop stays on the drones' network for the GCS, and node C's
  hotspot stays independent of the router's channel.
- **Cost:** one more program on the companion computer. UDP lines from anyone on the drones' network are
  accepted; that network is the team's own, with a password.

### Machine-readable lines on node C's USB: `@NODES` every 5 s and `@MSG` per message
- **Instead of:** parsing the human log lines, or the control room polling node C's web API.
- **Why:** JSON from ArduinoJson carries quotes, Hindi and missing fields safely; the node table is the same
  JSON as `/api/nodes`, so the control room reuses the monitor's tested code. The human log is unchanged.

### Control room: a separate page next to the GCS, using the GCS's API
- **Instead of:** adding a panel inside the GCS, or building video and map serving again.
- **Why:** the GCS is the team's own large program, already serving the ZR10 video as MJPEG, cached map
  tiles and a REST API with `goto`. The control room only reads those and sends `goto`, so the GCS is not
  changed and either can be restarted alone. Leaflet is copied in, so the page works without internet.

### Drone plan computed in the control room, flown only on the operator's word
- **Instead of:** the operator guessing where to hover the relay, or the control room flying drones by itself.
- **Why:** the control room already knows every node's position, the HQ's home and the drones' positions, so
  it can place relay points so no hop is longer than 80 % of the measured range, assign them to the relay
  drones, and check before take-off that node C, riding on the scout, stays in reach of the mesh along the
  whole flight. Each move still needs a click and a confirmation, and goes through the GCS.
- **How:** nearest ground node first, each joins the closest point already linked, with relays evenly spaced
  on that straight line. Simple to check by hand and right for a handful of nodes.
- **Cost:** no terrain, buildings, wind or battery in the plan; it is only as good as `--range`. For many
  nodes, a proper placement search would use fewer relays.

### Camera pulled straight from the Jetson, all the time (added 15 November 2026)
- **Instead of:** only through the GCS's video proxy.
- **Why:** the team wants the picture in the control room always. The GCS has to be running for its proxy,
  and it stops a stream 10 s after the last viewer leaves. `--camera rtsp://…` makes the control room pull
  the stream itself (OpenCV, already installed for the GCS) and keep the latest frame ready, GCS or not.
- **Cost:** with the GCS also showing the camera, the stream is pulled twice. Harmless on the Ethernet
  cable; over the drones' Wi-Fi it doubles the video traffic, so close one of the two viewers in flight.

### Node positions are set in the control room (added 15 November 2026)
- **Instead of:** only typing `pos lat lon` into each node over USB, or reflashing.
- **Why:** a node with no position cannot be drawn, so the map stayed empty although the nodes were
  connected, and the team wants to move nodes without touching them. In the control room a position is
  pasted as the maps app shows it (`28°44'58.3"N 77°06'53.1"E` or decimal) or clicked on the map. It is kept
  in `messages.jsonl` and used instead of the node's own; a connected drone's live GPS still wins.
- **Cost:** the node itself does not learn it, so other tools (the phone page, the monitor) do not see it.

### The scout flies only when an operator confirms
- **Instead of:** sending S-01 automatically on every SOS.
- **Why:** a message on an open hotspot is not proof of an emergency, and a drone flight is a safety
  decision. The GCS's `goto` switches S-01 to GUIDED; the pilot can take over from the GCS or the radio.

### Messages kept on the control room's disk (`messages.jsonl`)
- **Why:** node C keeps its inbox in memory and rides on a drone whose battery gets changed. The control room
  is where nothing may be lost, and it records what was done (scout sent, handled).
- **Cost:** the file holds people's messages; it is in `.gitignore` and must not be shared.

### Sender's location from node A's position and the phone's Wi-Fi signal, not the phone's GPS
- **Instead of:** the phone's GPS through the browser, or using the sender's mobile data.
- **Why:** browsers give location only to HTTPS pages. The node's page is plain HTTP with no internet, and
  an HTTPS page on the node would show every sender a certificate warning first, which a frightened person
  should not have to click through. Node A's position plus how strongly it hears the phone (1 byte in the
  packet) gives a search circle of about 10–150 m with nothing asked of the sender.
- **Cost:** a circle, not a point; the dBm-to-metres model is fixed until calibrated on site. The message
  room shrank from 38 to 37 bytes.
- **Later:** an HTTPS page on node A for exact phone GPS can be tried, if the certificate warning proves
  acceptable on real phones.

### City plan as a separate planning tool
- **Instead of:** claiming a Delhi-wide mesh works today.
- **Why:** it shows the idea with numbers (sites, HQs needed, hops) and states what the claim depends on:
  the link range between masts, which must be measured, and routing towards the nearest HQ, which today's
  flooding relay does not do. It works from real flag positions as soon as the team has them.

### Flights recorded before judging
- **Why:** flying is not allowed at the venue. The ground side runs live on the table with the drones parked
  and powered, and the videos show the same thing in the air.

## Electronics analysis

### Relays regenerate packets (decode-and-forward); no amplifier is added
- **Instead of:** an external amplifier or "boosting" weak packets before passing them on.
- **Why:** each relay already demodulates to bits, checks the CRC and sends a new packet at full power, so
  noise never builds up hop to hop (`electronics/relay_regeneration.py`: 3 hops at −13.5 dB each, 60 % against
  0 % for an amplifying relay). More transmit power would also break the 10 mW ERP limit.

### Python and LTspice for the analysis, not MATLAB
- **Instead of:** MATLAB.
- **Why:** MATLAB is not installed on the team laptop; Python (numpy, scipy, matplotlib) and LTspice are, so every
  script and circuit was run and checked here before it is shown. The Python maps line for line to MATLAB if
  a judge asks.

### Harmonic filter and supply capacitors as the hardware improvements
- **Why:** both fix real, measurable things. The 5th-order Chebyshev low-pass removes the 867 MHz and 1300 MHz
  harmonics (−25 and −46 dB in LTspice) at 0.24 dB cost; the 10 µF capacitor keeps the 3.3 V rail above the
  brown-out level during transmit bursts (2.62 V → 3.19 V in LTspice), which matches node B's restarts.

## Repository

### Private GitHub repository
- **Instead of:** public.
- **Why:** safer default. Commits carry the author's email address, which a public repository would show to
  everyone. It can be made public, or judges added as collaborators, at any time.
