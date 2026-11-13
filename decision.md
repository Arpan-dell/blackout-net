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

### Power: wall charger plus a power bank for the demonstration
- **Instead of:** wall charger only.
- **Why:** the team chose wall chargers for convenience. A project named BLACKOUT NET will be asked what
  happens in a blackout, so the demonstration still runs on power banks.

### Positions typed into each node's settings
- **Instead of:** a GPS module on every node, or the phone's location.
- **Why:** the nodes do not move, so a position read once from a maps app is enough and costs nothing. A GPS
  module needs open sky and gets no fix indoors. Browsers refuse location access on a plain-HTTP page such as
  http://192.168.4.1.
- **Cost:** someone has to enter the position whenever a node is moved.

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

### Text limit counted in bytes (38 for message plus landmark)
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

### Node B has no Wi-Fi
- **Instead of:** a hotspot on all three nodes.
- **Why:** B's only job is relaying. One setting in `config.h` turns its hotspot on if needed.

### Open hotspot, captive portal
- **Instead of:** a password-protected network.
- **Why:** anyone nearby must be able to ask for help without being told a password. The captive portal
  opens the page by itself when a phone joins.
- **Cost:** anyone in range can send requests. The firmware limits the queue, and the button has a 5 s
  lock, but there is no per-person limit yet.

### A and C on different Wi-Fi channels (1 and 6)
- **Why:** less interference between the two hotspots when the nodes are tested side by side.

### Separate "Acknowledge" for the coordinator
- **Instead of:** using the radio ACK as the coordinator's reply.
- **Why:** "delivered to HQ" and "a person at HQ has seen it" are different facts, and the handoff requires
  them to be kept apart.

### SOS button: hold 0.3 s, 5 s lock, ignored on the HQ node
- **Why:** the hold filters switch bounce and knocks on the box; the lock stops a stuck or repeatedly pressed
  button from flooding the channel; the HQ is the receiver, so an SOS from it has nowhere to go.

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

## Repository

### Private GitHub repository
- **Instead of:** public.
- **Why:** safer default. Commits carry the author's email address, which a public repository would show to
  everyone. It can be made public, or judges added as collaborators, at any time.
