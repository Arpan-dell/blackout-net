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
#define HAS_WIFI (NODE_ID != 2)  // B is a radio-only relay; change to 1 to give it a hotspot too

// ---- wiring: Ra-02 (SX1278) to ESP32 DevKit V1, same on every node ----
#define PIN_SCK 18
#define PIN_MISO 19
#define PIN_MOSI 23
#define PIN_NSS 21
#define PIN_RESET 14
#define PIN_DIO0 26
#define PIN_DIO1 27
#define PIN_BUTTON 25  // SOS push button to GND, uses the internal pull-up
#define PIN_LED 2      // status LED through 220 ohm to GND

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
