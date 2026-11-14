#pragma once
// BLACKOUT NET: every setting in one place. All nodes must be built from the same copy of this file.

// ---- identity: set per board in platformio.ini ----
#ifndef NODE_ID
#error "Build with -DNODE_ID=1 (A), 2 (B) or 3 (C), for example: pio run -e node_a"
#endif
#ifndef NODE_LAT
#define NODE_LAT 0.0  // 0, 0 = no position set
#endif
#ifndef NODE_LON
#define NODE_LON 0.0
#endif
#define HQ_ID 3                  // messages go to this node; it serves the HQ inbox
#define MAX_NODES 8              // ids 1..8 are shown as A..H
#define HAS_WIFI 1               // every node has a hotspot, so a phone can send an SOS through any of them

// ---- wiring: Ra-02 (SX1278). Two boards are supported; each picks its own pins when it is compiled ----
#if defined(ESP8266)  // NodeMCU (ESP-12E), as in the ESP8266 wiring diagram; D-numbers are the board's labels
#define PIN_SCK 14     // D5 (the ESP8266's fixed SPI pins)
#define PIN_MISO 12    // D6
#define PIN_MOSI 13    // D7
#define PIN_NSS 15     // D8
#define PIN_RESET 16   // D0
#define PIN_DIO0 4     // D2
#define PIN_DIO1 5     // D1
#define PIN_BUTTON 0   // D3, SOS button to GND. It is also the boot pin: do not hold it while powering on
#define PIN_LED 2      // D4, LED from 3V3 through 220 ohm: lit when the pin is LOW
#define LED_ON LOW
#else  // ESP32 DevKit V1
#define PIN_SCK 18
#define PIN_MISO 19
#define PIN_MOSI 23
#define PIN_NSS 21
#define PIN_RESET 14
#define PIN_DIO0 26
#define PIN_DIO1 27
#define PIN_BUTTON 25  // SOS push button to GND, uses the internal pull-up
#define PIN_LED 2      // status LED through 220 ohm to GND
#define LED_ON HIGH
#endif

// ---- coordinators: this PIN unlocks the HQ inbox, everyone's messages and the settings. CHANGE IT for the demo,
// and flash all nodes with the same one. The test scripts read it from this file.
#define COORD_PIN "202611"
#define MAX_OPEN_PER_PHONE 3  // a phone may have this many messages on their way at once

// ---- control room: every node prints its node table on USB this often (tools/control_room.py) ----
#define USB_STATUS_MS 5000

// ---- radio: must be identical on every node ----
#define LORA_FREQ_MHZ 433.5
#define LORA_BW_KHZ 125.0
#define LORA_SF 9
#define LORA_CR 7         // coding rate 4/7
#define LORA_SYNC 0x12    // private network
#define LORA_PREAMBLE 8
// Transmit power at the module, in dBm (2 to 17). This is NOT a statement of legal compliance:
// India's 433 MHz licence-exempt class is 10 mW ERP, and ERP depends on your antenna and cable.
// The team must verify the radiated power before raising this value.
#define LORA_TX_DBM 8

// ---- protocol timing ----
#define HB_INTERVAL_S 30          // heartbeat period per node
#define ACK_WAIT_MS 6000          // wait for the HQ's ACK: this long times the try number, plus jitter
#define MAX_TRIES 5               // then the message is EXPIRED
#define TX_GAP_MS 2500            // pause between this node's own messages, leaves air for relay and ACK
#define DATA_TTL 3                // hops a message may travel
#define DUTY_BUDGET_MS 360000UL   // most transmit time allowed in any hour (10 %)

// ---- bench test only ----
// On one table every node hears every other, so nothing needs the relay. Set to 1 and A and C ignore each
// other's direct packets, forcing A -> B -> C. This fakes distance: say so if you show it. Leave 0 for
// the real demonstration, where the A-C link is blocked physically.
#ifndef BENCH_BLOCK_DIRECT
#define BENCH_BLOCK_DIRECT 0
#endif
