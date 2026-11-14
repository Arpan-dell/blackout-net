// BLACKOUT NET node firmware: ESP32 DevKit V1 + Ai-Thinker Ra-02 (SX1278, 433 MHz).
// The same program runs on every node. A phone posts a message to node A over Wi-Fi, the message
// travels A -> B -> C by LoRa, and A shows DELIVERED only when C's ACK has come back.
#include <Arduino.h>
#include <ArduinoJson.h>
#include <DNSServer.h>
#include <RadioLib.h>
#include <SPI.h>
#if defined(ESP8266)  // NodeMCU (ESP-12E) boards
#include <EEPROM.h>
#include <ESP8266WebServer.h>
#include <ESP8266WiFi.h>
typedef ESP8266WebServer WebServer;
#else  // ESP32 DevKit boards
#include <Preferences.h>
#include <WebServer.h>
#include <WiFi.h>
#include <esp_netif.h>
#include <esp_wifi.h>
#if ESP_IDF_VERSION_MAJOR >= 5  // ESP32 Arduino core 3.x (Arduino IDE today); PlatformIO's 6.9.0 is core 2.x
#include <esp_wifi_ap_get_sta_list.h>
typedef wifi_sta_mac_ip_list_t StaIpList;
#define getStaIps esp_wifi_ap_get_sta_list_with_ip
#else
typedef esp_netif_sta_list_t StaIpList;
#define getStaIps esp_netif_get_sta_list
#endif
#endif
#include <stdarg.h>
#include <uri/UriBraces.h>

#include "config.h"
#include "page.h"

// ---------------------------------------------------------------- protocol
// Packet on the air: 13 header bytes, then 0..40 payload bytes. LoRa's own CRC guards the lot.
//   0 version | 1 type | 2 origin | 3 destination | 4-7 message id | 8 attempt | 9 ttl | 10 priority
//   11 last hop | 12 payload length
// DATA payload: category, sender's phone signal at the gateway (dBm, signed; 0 = unknown), text length,
//               text, landmark.
// HB payload:   uptime, latitude, longitude.
enum : uint8_t { T_DATA = 1, T_ACK = 2, T_HB = 3 };
enum : uint8_t { P_NORMAL = 0, P_SOS = 1 };
const uint8_t PROTO_VER = 3, HDR = 13, MAX_PAYLOAD = 40, BROADCAST = 0xFF;
const int32_t NO_POS = 0x7FFFFFFF;

struct Packet {
  uint8_t type, origin, dest, attempt, ttl, prio, lastHop, len;
  uint32_t id;
  uint8_t payload[MAX_PAYLOAD];
};

void put32(uint8_t *b, uint32_t v) {
  b[0] = v >> 24; b[1] = v >> 16; b[2] = v >> 8; b[3] = v;
}
uint32_t get32(const uint8_t *b) {
  return (uint32_t)b[0] << 24 | (uint32_t)b[1] << 16 | (uint32_t)b[2] << 8 | b[3];
}

size_t encode(const Packet &p, uint8_t *b) {
  b[0] = PROTO_VER; b[1] = p.type; b[2] = p.origin; b[3] = p.dest;
  put32(b + 4, p.id);
  b[8] = p.attempt; b[9] = p.ttl; b[10] = p.prio; b[11] = p.lastHop; b[12] = p.len;
  memcpy(b + HDR, p.payload, p.len);
  return HDR + p.len;
}

bool validNode(uint8_t id) { return id >= 1 && id <= MAX_NODES; }

// Anything that arrives by radio is untrusted: reject whatever is not exactly a packet of ours.
bool decode(const uint8_t *b, size_t n, Packet &p) {
  if (n < HDR || b[0] != PROTO_VER || b[12] > MAX_PAYLOAD || n != (size_t)HDR + b[12]) return false;
  p.type = b[1]; p.origin = b[2]; p.dest = b[3]; p.id = get32(b + 4);
  p.attempt = b[8]; p.ttl = b[9]; p.prio = b[10]; p.lastHop = b[11]; p.len = b[12];
  if (p.type < T_DATA || p.type > T_HB || !validNode(p.origin) || !validNode(p.lastHop)) return false;
  if (!validNode(p.dest) && p.dest != BROADCAST) return false;
  if (p.prio > P_SOS) return false;
  memcpy(p.payload, b + HDR, p.len);
  return true;
}

// Duplicate filter. The attempt number is part of the key, so a retry is relayed again
// while the echo of a packet already handled is dropped.
struct Seen { uint8_t origin, type, attempt; uint32_t id; };
Seen seen[48];
uint8_t seenAt = 0;

bool seenBefore(const Packet &p) {
  for (const Seen &s : seen)
    if (s.origin == p.origin && s.type == p.type && s.attempt == p.attempt && s.id == p.id) return true;
  seen[seenAt] = {p.origin, p.type, p.attempt, p.id};
  seenAt = (seenAt + 1) % (sizeof(seen) / sizeof(seen[0]));
  return false;
}

// ---------------------------------------------------------------- state
enum : uint8_t { S_QUEUED, S_TRANSMITTING, S_WAITING_ACK, S_DELIVERED, S_EXPIRED };
const char *const STATE_NAME[] = {"queued", "transmitting", "waiting_ack", "delivered", "expired"};
const char *const CATEGORY[] = {"medical", "fire", "trapped", "supplies", "security", "other"};
const uint8_t CAT_COUNT = 6, CAT_OTHER = 5;
const uint8_t TEXT_ROOM = MAX_PAYLOAD - 3;  // bytes shared by text and landmark

struct Msg {  // a message this node originated
  bool used;
  uint8_t prio, cat, tries, state, ackVia;
  int8_t phoneRssi;
  uint32_t id, order, createdMs, retryAtMs, doneMs;
  float ackRssi;
  char text[TEXT_ROOM + 1], landmark[TEXT_ROOM + 1];
};
struct Ticket {  // a message addressed to this node (the HQ inbox)
  bool used, acked;
  uint8_t origin, prio, cat, via;
  int8_t phoneRssi;
  uint32_t id, arrivedMs;
  float rssi, snr;
  char text[TEXT_ROOM + 1], landmark[TEXT_ROOM + 1];
};
struct Pending {  // a ready packet waiting for the radio: forwards, ACKs, heartbeats
  bool used;
  uint32_t notBeforeMs, order;
  Packet p;
};
struct Peer {  // another node, as last heard through its heartbeat
  bool known;
  uint8_t via;
  uint32_t seenMs, seq, uptimeS;
  int32_t latE6, lonE6;
  float rssi, snr;
};
struct Stats {
  uint32_t tx, rx, forwarded, duplicates, crcErrors, badPackets, dropped, retries, delivered, expired, deferred;
};

Msg outbox[32];
Ticket inbox[32];
Pending txq[12];
Peer peers[MAX_NODES + 1];
Stats stats;

SX1278 radio = new Module(PIN_NSS, PIN_DIO0, PIN_RESET, PIN_DIO1);
WebServer server(80);
DNSServer dns;

bool radioOk = false, priorityOn = true;
int radioError = 0;
volatile bool dio0Flag = false;
uint32_t nextId, orderCounter = 0, hbSeq = 0, nextHbMs = 0, nextOwnTxMs = 0;
uint32_t lastRxMs = 0, lastDeliveredMs = 0;
float lastRssi = NAN, lastSnr = NAN;

char nodeChar(uint8_t id) { return 'A' + id - 1; }
String nodeName(uint8_t id) { return String(nodeChar(id)); }

// This node's position: typed in over USB (kept in flash), else NODE_LAT / NODE_LON from platformio.ini.
// Sent in every heartbeat. Nodes riding on drones get their live position from the drone, in the control room.
int32_t posLatE6 = NO_POS, posLonE6 = NO_POS;
const char *posSource = "none";  // saved | build | none

// ---------------------------------------------------------------- log (serial + last lines for the web page)
char logRing[40][112];
uint8_t logAt = 0;

void logf(const char *fmt, ...) {
  char *line = logRing[logAt];
  logAt = (logAt + 1) % 40;
  int n = snprintf(line, sizeof(logRing[0]), "[%8lu ms] ", (unsigned long)millis());
  va_list args;
  va_start(args, fmt);
  vsnprintf(line + n, sizeof(logRing[0]) - n, fmt, args);
  va_end(args);
  Serial.println(line);
}

// ---------------------------------------------------------------- airtime budget (sliding hour, one bucket per minute)
uint32_t airBucket[60];
uint8_t airAt = 0;
uint32_t airMinuteStart = 0;

void airRotate() {
  while (millis() - airMinuteStart >= 60000UL) {
    airMinuteStart += 60000UL;
    airAt = (airAt + 1) % 60;
    airBucket[airAt] = 0;
  }
}
uint32_t airtimeUsedMs() {
  airRotate();
  uint32_t sum = 0;
  for (uint32_t b : airBucket) sum += b;
  return sum;
}

// ---------------------------------------------------------------- radio
void IRAM_ATTR onDio0() { dio0Flag = true; }

bool transmit(Packet &p) {
  uint8_t buf[HDR + MAX_PAYLOAD];
  p.lastHop = NODE_ID;
  size_t n = encode(p, buf);
  uint32_t airMs = radio.getTimeOnAir(n) / 1000;
  int st = radio.transmit(buf, n);  // blocks for the airtime: 0.2 to 0.45 s at SF9
  airRotate();
  airBucket[airAt] += airMs;
  stats.tx++;
  dio0Flag = false;
  radio.startReceive();
  const char *kind = p.type == T_DATA ? "DATA" : p.type == T_ACK ? "ACK" : "HB";
  if (st != RADIOLIB_ERR_NONE) {
    logf("TX FAILED code %d: %s #%lu", st, kind, (unsigned long)p.id);
    return false;
  }
  if (p.type != T_HB || p.origin != NODE_ID)  // our own heartbeats would drown the log
    logf("TX %s #%lu try %u origin %c -> %c ttl %u %s, %lu ms on air", kind, (unsigned long)p.id, p.attempt,
         nodeChar(p.origin), p.dest == BROADCAST ? '*' : nodeChar(p.dest), p.ttl,
         p.prio == P_SOS ? "SOS" : "normal", (unsigned long)airMs);
  return true;
}

bool enqueue(const Packet &p, uint32_t delayMs) {
  for (Pending &q : txq)
    if (!q.used) {
      q = {true, millis() + delayMs, orderCounter++, p};
      return true;
    }
  stats.dropped++;
  logf("DROP: transmit queue full");
  return false;
}

// Listen before talk: do not start while the radio is locking on to somebody else's packet.
bool channelBusy() {
  static uint32_t busySince = 0;
  if (!(radio.getModemStatus() & 0x03)) {  // signal detected | signal synchronised
    busySince = 0;
    return false;
  }
  uint32_t now = millis();
  if (!busySince) busySince = now | 1;
  return now - busySince < 1500;  // a stuck flag must not silence the node for good
}

// ---------------------------------------------------------------- messages this node originates
Msg *queueMessage(uint8_t prio, uint8_t cat, const char *text, const char *landmark, int8_t phoneRssi) {
  Msg *slot = nullptr;
  for (Msg &m : outbox)  // a free slot, else the oldest finished message
    if (!m.used) { slot = &m; break; }
  if (!slot)
    for (Msg &m : outbox)
      if (m.state >= S_DELIVERED && (!slot || (int32_t)(m.order - slot->order) < 0)) slot = &m;
  if (!slot) return nullptr;
  *slot = {};
  slot->used = true;
  slot->prio = prio;
  slot->cat = cat;
  slot->phoneRssi = phoneRssi;
  slot->id = nextId++;
  slot->order = orderCounter++;
  slot->createdMs = millis();
  strlcpy(slot->text, text, sizeof(slot->text));
  strlcpy(slot->landmark, landmark, sizeof(slot->landmark));
  logf("QUEUED #%lu %s %s \"%s\"", (unsigned long)slot->id, prio == P_SOS ? "SOS" : "normal", CATEGORY[cat], text);
  return slot;
}

bool isDue(const Msg &m, uint32_t now) {
  return m.used && (m.state == S_QUEUED || (m.state == S_WAITING_ACK && (int32_t)(now - m.retryAtMs) >= 0));
}

// The scheduler under test: SOS first when priority is on, plain first-in-first-out when it is off.
Msg *nextDue(uint32_t now) {
  Msg *best = nullptr;
  for (Msg &m : outbox) {
    if (!isDue(m, now)) continue;
    bool higher = priorityOn && best && m.prio > best->prio;
    bool sameClass = best && (!priorityOn || m.prio == best->prio);
    if (!best || higher || (sameClass && (int32_t)(m.order - best->order) < 0)) best = &m;
  }
  return best;
}

void expireMessages() {
  uint32_t now = millis();
  for (Msg &m : outbox)
    if (m.used && m.state == S_WAITING_ACK && m.tries >= MAX_TRIES && (int32_t)(now - m.retryAtMs) >= 0) {
      m.state = S_EXPIRED;
      m.doneMs = now;
      stats.expired++;
      logf("EXPIRED #%lu: no ACK after %u tries", (unsigned long)m.id, m.tries);
    }
}

Packet dataPacket(const Msg &m, uint8_t attempt) {
  Packet p = {};
  p.type = T_DATA; p.origin = NODE_ID; p.dest = HQ_ID; p.id = m.id;
  p.attempt = attempt; p.ttl = DATA_TTL; p.prio = m.prio; p.lastHop = NODE_ID;
  uint8_t tl = strlen(m.text), ll = strlen(m.landmark);
  p.payload[0] = m.cat;
  p.payload[1] = (uint8_t)m.phoneRssi;
  p.payload[2] = tl;
  memcpy(p.payload + 3, m.text, tl);
  memcpy(p.payload + 3 + tl, m.landmark, ll);
  p.len = 3 + tl + ll;
  return p;
}

void sendOwn(Msg &m) {
  Packet p = dataPacket(m, ++m.tries);
  if (m.tries > 1) stats.retries++;
  m.state = S_TRANSMITTING;
  transmit(p);  // a TX-done is not a delivery: only the HQ's ACK moves this on to DELIVERED
  m.state = S_WAITING_ACK;
  m.retryAtMs = millis() + (uint32_t)ACK_WAIT_MS * m.tries + random(0, 2000);
  nextOwnTxMs = millis() + TX_GAP_MS + random(0, 500);
}

void pumpTx() {
  uint32_t now = millis();
  Pending *q = nullptr;
  for (Pending &c : txq) {  // relayed packets and ACKs go before this node's own messages
    if (!c.used || (int32_t)(now - c.notBeforeMs) < 0) continue;
    bool higher = priorityOn && q && c.p.prio > q->p.prio;
    bool sameClass = q && (!priorityOn || c.p.prio == q->p.prio);
    if (!q || higher || (sameClass && (int32_t)(c.order - q->order) < 0)) q = &c;
  }
  Msg *m = q || (int32_t)(now - nextOwnTxMs) < 0 ? nullptr : nextDue(now);
  if (!q && !m) return;
  if (airtimeUsedMs() >= DUTY_BUDGET_MS) {  // the hour's transmit budget is spent: stay silent
    static uint32_t lastNote = 0;
    if (now - lastNote > 10000) {
      lastNote = now;
      stats.deferred++;
      logf("HOLD: airtime budget for this hour is used up");
    }
    return;
  }
  if (channelBusy()) return;
  if (q) {
    q->used = false;
    transmit(q->p);
  } else {
    sendOwn(*m);
  }
}

// ---------------------------------------------------------------- receiving
void fillTicket(JsonObject o, const Ticket &t);  // in the web API section

void storeTicket(const Packet &p, float rssi, float snr) {
  for (const Ticket &t : inbox)  // a retry of a message already in the inbox: ACK it again, store nothing
    if (t.used && t.origin == p.origin && t.id == p.id) return;
  Ticket *slot = nullptr;
  for (Ticket &t : inbox)
    if (!t.used) { slot = &t; break; }
  if (!slot)  // full: reuse the oldest acknowledged ticket, else the oldest of all
    for (Ticket &t : inbox)
      if (!slot || (t.acked && !slot->acked) ||
          (t.acked == slot->acked && (int32_t)(t.arrivedMs - slot->arrivedMs) < 0))
        slot = &t;
  uint8_t tl = p.payload[2];
  *slot = {};
  slot->used = true;
  slot->origin = p.origin;
  slot->prio = p.prio;
  slot->cat = p.payload[0] < CAT_COUNT ? p.payload[0] : CAT_OTHER;
  slot->phoneRssi = (int8_t)p.payload[1];
  slot->via = p.lastHop;
  slot->id = p.id;
  slot->arrivedMs = millis();
  slot->rssi = rssi;
  slot->snr = snr;
  memcpy(slot->text, p.payload + 3, tl);
  memcpy(slot->landmark, p.payload + 3 + tl, p.len - 3 - tl);
  logf("INBOX #%lu from %c %s \"%s\"", (unsigned long)p.id, nodeChar(p.origin), p.prio == P_SOS ? "SOS" : "normal",
       slot->text);
  // For tools/control_room.py on the USB port: one JSON line, with where the sending node stands.
  JsonDocument doc;
  fillTicket(doc.to<JsonObject>(), *slot);
  const Peer &from = peers[p.origin];
  int32_t la = p.origin == NODE_ID ? posLatE6 : from.known ? from.latE6 : NO_POS;
  int32_t lo = p.origin == NODE_ID ? posLonE6 : from.known ? from.lonE6 : NO_POS;
  if (la != NO_POS && lo != NO_POS) {
    doc["lat"] = la / 1e6;
    doc["lon"] = lo / 1e6;
  }
  Serial.print("@MSG ");
  serializeJson(doc, Serial);
  Serial.println();
}

void markDelivered(const Packet &p, float rssi) {
  for (Msg &m : outbox)
    if (m.used && m.id == p.id && m.state != S_DELIVERED) {
      if (m.state == S_EXPIRED) stats.expired--;  // a late ACK: it did arrive after all
      m.state = S_DELIVERED;
      m.doneMs = millis();
      m.ackVia = p.lastHop;
      m.ackRssi = rssi;
      stats.delivered++;
      lastDeliveredMs = m.doneMs | 1;
      logf("DELIVERED #%lu: ACK from %c in %lu ms on try %u", (unsigned long)m.id, nodeChar(p.origin),
           (unsigned long)(m.doneMs - m.createdMs), m.tries);
    }
}

// Every node takes messages from phones. On the HQ there is nothing to send: it goes straight into the inbox.
Msg *newMessage(uint8_t prio, uint8_t cat, const char *text, const char *landmark, int8_t phoneRssi) {
  Msg *m = queueMessage(prio, cat, text, landmark, phoneRssi);
  if (!m || NODE_ID != HQ_ID) return m;
  m->tries = 1;
  storeTicket(dataPacket(*m, 1), NAN, NAN);
  m->state = S_DELIVERED;
  m->doneMs = millis();
  m->ackVia = NODE_ID;
  stats.delivered++;
  lastDeliveredMs = m->doneMs | 1;
  logf("DELIVERED #%lu: sent through the HQ itself", (unsigned long)m->id);
  return m;
}

void noteHeartbeat(const Packet &p, float rssi, float snr) {
  if (p.len != 12) { stats.badPackets++; return; }
  Peer &peer = peers[p.origin];
  if (!peer.known) logf("NEW NODE %c heard via %c", nodeChar(p.origin), nodeChar(p.lastHop));
  peer.known = true;
  peer.via = p.lastHop;
  peer.seenMs = millis();
  peer.seq = p.id;
  peer.uptimeS = get32(p.payload);
  peer.latE6 = (int32_t)get32(p.payload + 4);
  peer.lonE6 = (int32_t)get32(p.payload + 8);
  peer.rssi = rssi;
  peer.snr = snr;
}

void handlePacket(Packet &p, float rssi, float snr) {
  if (p.origin == NODE_ID) return;  // our own packet coming back from a relay
#if BENCH_BLOCK_DIRECT
  if ((NODE_ID == 1 && p.lastHop == HQ_ID) || (NODE_ID == HQ_ID && p.lastHop == 1)) return;
#endif
  const char *kind = p.type == T_DATA ? "DATA" : p.type == T_ACK ? "ACK" : "HB";
  bool dup = seenBefore(p);
  if (dup) stats.duplicates++;
  if (p.type != T_HB)
    logf("RX %s #%lu try %u origin %c -> %c from %c rssi %.0f snr %.1f%s", kind, (unsigned long)p.id, p.attempt,
         nodeChar(p.origin), p.dest == BROADCAST ? '*' : nodeChar(p.dest), nodeChar(p.lastHop), rssi, snr,
         dup ? " (duplicate)" : "");
  if (dup) return;

  if (p.type == T_HB) {
    noteHeartbeat(p, rssi, snr);
  } else if (p.dest == NODE_ID) {
    if (p.type == T_ACK) {
      markDelivered(p, rssi);
    } else if (p.len < 3 || 3 + p.payload[2] > p.len) {
      stats.badPackets++;
    } else {
      storeTicket(p, rssi, snr);
      Packet ack = {};  // end-to-end ACK back to the origin, one for every try that reaches us
      ack.type = T_ACK; ack.origin = NODE_ID; ack.dest = p.origin; ack.id = p.id;
      ack.attempt = p.attempt; ack.ttl = DATA_TTL; ack.prio = p.prio;
      enqueue(ack, random(150, 350));
    }
    return;  // addressed to us: never relayed further
  }
  if (p.ttl <= 1) return;
  p.ttl--;
  if (enqueue(p, random(100, 400))) {  // jitter, so two relays that heard the same packet do not collide
    stats.forwarded++;
    if (p.type != T_HB) logf("RELAY %s #%lu origin %c -> %c", kind, (unsigned long)p.id, nodeChar(p.origin), nodeChar(p.dest));
  }
}

void pollRadio() {
  if (!dio0Flag) return;
  dio0Flag = false;
  uint8_t buf[HDR + MAX_PAYLOAD];
  size_t n = radio.getPacketLength();
  if (n == 0 || n > sizeof(buf)) {
    stats.badPackets++;
    radio.startReceive();
    return;
  }
  int st = radio.readData(buf, n);
  float rssi = radio.getRSSI(), snr = radio.getSNR();
  radio.startReceive();
  if (st == RADIOLIB_ERR_CRC_MISMATCH) { stats.crcErrors++; return; }
  Packet p;
  if (st != RADIOLIB_ERR_NONE || !decode(buf, n, p)) { stats.badPackets++; return; }
  stats.rx++;
  lastRxMs = millis() | 1;
  lastRssi = rssi;
  lastSnr = snr;
  handlePacket(p, rssi, snr);
}

void heartbeatTick() {
  if ((int32_t)(millis() - nextHbMs) < 0) return;
  nextHbMs = millis() + HB_INTERVAL_S * 1000UL + random(0, 2000);
  Packet p = {};
  p.type = T_HB; p.origin = NODE_ID; p.dest = BROADCAST; p.id = ++hbSeq; p.ttl = 2; p.len = 12;
  put32(p.payload, millis() / 1000);
  put32(p.payload + 4, (uint32_t)posLatE6);
  put32(p.payload + 8, (uint32_t)posLonE6);
  enqueue(p, 0);
}

// ---------------------------------------------------------------- SOS button and status LED
void pollButton() {
  static uint32_t downAt = 0, lastSos = 0;
  static bool fired = false;
  if (digitalRead(PIN_BUTTON) == HIGH) {
    downAt = 0;
    fired = false;
    return;
  }
  uint32_t now = millis();
  if (!downAt) downAt = now | 1;
  if (fired || now - downAt < 300) return;  // hold for 0.3 s: debounce, and a knock on the box is not an SOS
  fired = true;
  if (lastSos && now - lastSos < 5000) {
    logf("BUTTON ignored: an SOS was sent less than 5 s ago");
    return;
  }
  lastSos = now | 1;
  char where[8];
  snprintf(where, sizeof(where), "Node %c", nodeChar(NODE_ID));
  if (!newMessage(P_SOS, CAT_OTHER, "SOS button pressed", where, 0)) logf("BUTTON: queue full, SOS not queued");
}

// LED: fast blink = own message waiting for its ACK; 3 s solid = delivered; short flick = packet received.
// On the HQ it stays on while an SOS ticket is unacknowledged. Slow blink = radio did not start.
void updateLed() {
  uint32_t now = millis();
  bool on = lastRxMs && now - lastRxMs < 60;
  if (!radioOk) {
    on = (now / 500) % 2;
  } else if (NODE_ID == HQ_ID) {
    for (const Ticket &t : inbox)
      if (t.used && !t.acked && t.prio == P_SOS) on = true;
  } else {
    bool waiting = false;
    for (const Msg &m : outbox)
      if (m.used && m.state < S_DELIVERED) waiting = true;
    if (waiting) on = (now / 100) % 2;
    else if (lastDeliveredMs && now - lastDeliveredMs < 3000) on = true;
  }
  digitalWrite(PIN_LED, on ? LED_ON : !LED_ON);
}

// ---------------------------------------------------------------- web API
void sendJson(int code, JsonDocument &doc) {
  String body;
  serializeJson(doc, body);
  server.send(code, "application/json", body);
}
void sendError(int code, const char *message) {
  JsonDocument doc;
  doc["error"] = message;
  sendJson(code, doc);
}

void fillMsg(JsonObject o, const Msg &m) {
  o["message_id"] = m.id;
  o["type"] = m.prio == P_SOS ? "SOS" : "NORMAL";
  o["category"] = CATEGORY[m.cat];
  o["text"] = m.text;
  o["landmark"] = m.landmark;
  o["status"] = STATE_NAME[m.state];
  o["tries"] = m.tries;
  o["max_tries"] = MAX_TRIES;
  o["age_ms"] = millis() - m.createdMs;
  if (m.state == S_DELIVERED) {
    o["latency_ms"] = m.doneMs - m.createdMs;
    o["ack_via"] = nodeName(m.ackVia);
    o["ack_rssi"] = m.ackRssi;
  }
}
void fillTicket(JsonObject o, const Ticket &t) {
  o["message_id"] = t.id;
  o["origin"] = nodeName(t.origin);
  o["type"] = t.prio == P_SOS ? "SOS" : "NORMAL";
  o["category"] = CATEGORY[t.cat];
  o["text"] = t.text;
  o["landmark"] = t.landmark;
  o["age_ms"] = millis() - t.arrivedMs;
  o["via"] = nodeName(t.via);
  o["rssi"] = t.rssi;
  o["snr"] = t.snr;
  if (t.phoneRssi) o["phone_rssi"] = t.phoneRssi;  // the sender's phone as heard by its gateway's Wi-Fi
  o["acknowledged"] = t.acked;
}

// Signal strength of the phone at this IP address, as this node's hotspot hears it; 0 if not found.
#if defined(ESP8266)
int8_t phoneRssi(IPAddress) { return 0; }  // the ESP8266 cannot tell its hotspot's phones apart by signal
#else
int8_t phoneRssi(IPAddress ip) {
  wifi_sta_list_t wl;
  StaIpList nl;
  if (esp_wifi_ap_get_sta_list(&wl) != ESP_OK || getStaIps(&wl, &nl) != ESP_OK) return 0;
  for (int i = 0; i < nl.num; i++)
    if (IPAddress(nl.sta[i].ip.addr) == ip) return wl.sta[i].rssi;
  return 0;
}
#endif

void apiSend() {
  JsonDocument in;
  if (deserializeJson(in, server.arg("plain"))) return sendError(400, "The request body must be JSON");
  const char *text = in["text"] | "", *landmark = in["landmark"] | "";
  const char *type = in["type"] | "NORMAL", *category = in["category"] | "other";
  if (strlen(text) + strlen(landmark) > TEXT_ROOM)
    return sendError(400, ("Message plus landmark must fit in " + String(TEXT_ROOM) + " bytes").c_str());
  uint8_t cat = CAT_OTHER;
  for (uint8_t i = 0; i < CAT_COUNT; i++)
    if (!strcasecmp(category, CATEGORY[i])) cat = i;
  Msg *m = newMessage(!strcasecmp(type, "SOS") ? P_SOS : P_NORMAL, cat, text, landmark,
                        phoneRssi(server.client().remoteIP()));
  if (!m) return sendError(429, "The queue is full: wait for earlier messages to finish");
  JsonDocument out;
  out["message_id"] = m->id;
  out["status"] = "queued";
  sendJson(202, out);
}

void apiMessages() {
  JsonDocument doc;
  doc["node"] = nodeName(NODE_ID);
  JsonArray out = doc["outbox"].to<JsonArray>(), in = doc["inbox"].to<JsonArray>();
  for (const Msg &m : outbox)
    if (m.used) fillMsg(out.add<JsonObject>(), m);
  for (const Ticket &t : inbox)
    if (t.used) fillTicket(in.add<JsonObject>(), t);
  sendJson(200, doc);
}

void apiMessageById() {
  uint32_t id = strtoul(server.pathArg(0).c_str(), nullptr, 10);
  JsonDocument doc;
  for (const Msg &m : outbox)
    if (m.used && m.id == id) {
      fillMsg(doc.to<JsonObject>(), m);
      return sendJson(200, doc);
    }
  for (const Ticket &t : inbox)
    if (t.used && t.id == id) {
      fillTicket(doc.to<JsonObject>(), t);
      return sendJson(200, doc);
    }
  sendError(404, "No message with that id on this node");
}

// The coordinator's own "I have seen this". It stays on the HQ and is not a radio ACK.
void apiTicketAck() {
  uint32_t id = strtoul(server.pathArg(0).c_str(), nullptr, 10);
  for (Ticket &t : inbox)
    if (t.used && t.id == id) {
      t.acked = true;
      logf("OPERATOR acknowledged #%lu", (unsigned long)id);
      JsonDocument doc;
      doc["message_id"] = id;
      doc["acknowledged"] = true;
      return sendJson(200, doc);
    }
  sendError(404, "No ticket with that id");
}

void apiStatus() {
  JsonDocument doc;
  uint32_t queued = 0, waiting = 0, relayQueue = 0, openTickets = 0;
  for (const Msg &m : outbox) {
    if (m.used && m.state == S_QUEUED) queued++;
    if (m.used && m.state == S_WAITING_ACK) waiting++;
  }
  for (const Pending &q : txq) relayQueue += q.used;
  for (const Ticket &t : inbox) openTickets += t.used && !t.acked;
  doc["node"] = nodeName(NODE_ID);
  doc["role"] = NODE_ID == HQ_ID ? "hq" : HAS_WIFI ? "gateway" : "relay";
  doc["hq"] = nodeName(HQ_ID);
  doc["uptime_s"] = millis() / 1000;
  doc["wifi_clients"] = HAS_WIFI ? WiFi.softAPgetStationNum() : 0;
  doc["priority"] = priorityOn;
  doc["bench_block_direct"] = (bool)BENCH_BLOCK_DIRECT;
  doc["text_room_bytes"] = TEXT_ROOM;
  JsonObject r = doc["radio"].to<JsonObject>();
  r["ok"] = radioOk;
  r["error_code"] = radioError;
  r["chip"] = "SX1278";
  r["freq_mhz"] = LORA_FREQ_MHZ;
  r["bw_khz"] = LORA_BW_KHZ;
  r["sf"] = LORA_SF;
  r["cr"] = LORA_CR;
  r["tx_dbm_setting"] = LORA_TX_DBM;
  r["last_rssi"] = lastRssi;
  r["last_snr"] = lastSnr;
  JsonObject q = doc["queues"].to<JsonObject>();
  q["queued"] = queued;
  q["waiting_ack"] = waiting;
  q["relay"] = relayQueue;
  q["open_tickets"] = openTickets;
  JsonObject c = doc["counters"].to<JsonObject>();
  c["sent"] = stats.tx;
  c["received"] = stats.rx;
  c["relayed"] = stats.forwarded;
  c["duplicates"] = stats.duplicates;
  c["crc_errors"] = stats.crcErrors;
  c["bad_packets"] = stats.badPackets;
  c["dropped"] = stats.dropped;
  c["retries"] = stats.retries;
  c["delivered"] = stats.delivered;
  c["expired"] = stats.expired;
  if (stats.delivered + stats.expired) doc["delivery_pct"] = 100.0 * stats.delivered / (stats.delivered + stats.expired);
  doc["airtime_ms_last_hour"] = airtimeUsedMs();
  doc["airtime_budget_ms"] = DUTY_BUDGET_MS;
  sendJson(200, doc);
}

// Shape agreed with tools/monitor.py and tools/control_room.py.
void nodesJson(JsonDocument &doc) {
  JsonObject self = doc["self"].to<JsonObject>();
  self["name"] = nodeName(NODE_ID);
  self["uptime_s"] = millis() / 1000;
  self["wifi_clients"] = HAS_WIFI ? WiFi.softAPgetStationNum() : 0;
  if (posLatE6 != NO_POS) {
    self["lat"] = posLatE6 / 1e6;
    self["lon"] = posLonE6 / 1e6;
  }
  self["pos_src"] = posSource;
  doc["hb_interval_s"] = HB_INTERVAL_S;
  JsonArray nodes = doc["nodes"].to<JsonArray>();
  for (uint8_t id = 1; id <= MAX_NODES; id++) {
    const Peer &p = peers[id];
    if (!p.known) continue;
    JsonObject n = nodes.add<JsonObject>();
    n["id"] = id;
    n["name"] = nodeName(id);
    n["age_ms"] = millis() - p.seenMs;
    n["seq"] = p.seq;
    n["via"] = nodeName(p.via);
    n["rssi"] = p.rssi;
    n["snr"] = p.snr;
    n["uptime_s"] = p.uptimeS;
    if (p.latE6 != NO_POS && p.lonE6 != NO_POS) {
      n["lat"] = p.latE6 / 1e6;
      n["lon"] = p.lonE6 / 1e6;
    }
  }
}

void apiNodes() {
  JsonDocument doc;
  nodesJson(doc);
  sendJson(200, doc);
}

// ---------------------------------------------------------------- position, USB commands, USB status
// "28.749912 77.116403" -> millionths of a degree. False unless both are numbers in range and not 0, 0.
bool parsePos(const char *s, int32_t &lat, int32_t &lon) {
  char *end;
  double la = strtod(s, &end);
  if (end == s) return false;
  const char *rest = end;
  double lo = strtod(rest, &end);
  if (end == rest || fabs(la) > 90 || fabs(lo) > 180 || (la == 0 && lo == 0)) return false;
  while (*end == ' ' || *end == '\r') end++;
  if (*end) return false;
  lat = lround(la * 1e6);
  lon = lround(lo * 1e6);
  return true;
}

// Where the typed position is kept, and the hardware random numbers: the two boards do these differently.
#if defined(ESP8266)
const uint32_t POS_MAGIC = 0x424E5031;  // "BNP1": marks the 12 bytes of emulated EEPROM as a saved position
void storeBegin() { EEPROM.begin(12); }
bool storedPos(int32_t &la, int32_t &lo) {
  uint32_t magic;
  EEPROM.get(0, magic);
  EEPROM.get(4, la);
  EEPROM.get(8, lo);
  return magic == POS_MAGIC;
}
void storePos(int32_t la, int32_t lo) {
  EEPROM.put(0, POS_MAGIC);
  EEPROM.put(4, la);
  EEPROM.put(8, lo);
  EEPROM.commit();
}
void forgetPos() {
  EEPROM.put(0, (uint32_t)0);
  EEPROM.commit();
}
uint32_t hwRandom() { return ESP.random(); }
#else
Preferences prefs;
void storeBegin() { prefs.begin("blackout"); }
bool storedPos(int32_t &la, int32_t &lo) {
  if (!prefs.isKey("lat")) return false;
  la = prefs.getInt("lat");
  lo = prefs.getInt("lon");
  return true;
}
void storePos(int32_t la, int32_t lo) {
  prefs.putInt("lat", la);
  prefs.putInt("lon", lo);
}
void forgetPos() {
  prefs.remove("lat");
  prefs.remove("lon");
}
uint32_t hwRandom() { return esp_random(); }
#endif

void loadPosition() {  // the position saved over USB, else the one in platformio.ini
  int32_t la, lo;
  if (storedPos(la, lo)) {
    posLatE6 = la;
    posLonE6 = lo;
    posSource = "saved";
  } else if (NODE_LAT != 0.0 || NODE_LON != 0.0) {
    posLatE6 = lround(NODE_LAT * 1e6);
    posLonE6 = lround(NODE_LON * 1e6);
    posSource = "build";
  } else {
    posLatE6 = posLonE6 = NO_POS;
    posSource = "none";
  }
}

// Typed on the serial monitor (115200 baud, newline):  pos 28.749912 77.116403   or   pos clear
void serialTick() {
  static char line[64];
  static uint8_t len = 0;
  while (Serial.available()) {
    char c = Serial.read();
    if (c != '\n') {
      if (len < sizeof(line) - 1) line[len++] = c;
      continue;
    }
    line[len] = 0;
    len = 0;
    int32_t la, lo;
    if (!strncmp(line, "pos clear", 9)) {
      forgetPos();
      loadPosition();
      logf("POSITION cleared, now %s", posSource);
    } else if (!strncmp(line, "pos ", 4) && parsePos(line + 4, la, lo)) {
      storePos(la, lo);
      loadPosition();
      logf("POSITION saved: %.6f, %.6f", la / 1e6, lo / 1e6);
    } else if (line[0] && line[0] != '\r') {
      logf("USB command not understood. Use: pos <latitude> <longitude>   or   pos clear");
    }
  }
}

// Every node prints its node table on USB every few seconds, so tools/control_room.py works plugged into
// any of them (node C in the field, any node while testing). Messages (@MSG) come from the HQ only.
void statusTick() {
  static uint32_t next = 0;
  if ((int32_t)(millis() - next) < 0) return;
  next = millis() + USB_STATUS_MS;
  JsonDocument doc;
  nodesJson(doc);
  Serial.print("@NODES ");
  serializeJson(doc, Serial);
  Serial.println();
}

void apiMode() {  // POST /api/mode?priority=0|1, for the priority-versus-FIFO test
  if (!server.hasArg("priority")) return sendError(400, "Give priority=1 or priority=0");
  priorityOn = server.arg("priority") == "1";
  logf("MODE: %s", priorityOn ? "SOS priority" : "plain FIFO");
  JsonDocument doc;
  doc["priority"] = priorityOn;
  sendJson(200, doc);
}

void apiLog() {
  JsonDocument doc;
  JsonArray lines = doc["lines"].to<JsonArray>();
  for (uint8_t i = 0; i < 40; i++) {
    const char *line = logRing[(logAt + i) % 40];
    if (line[0]) lines.add(line);
  }
  sendJson(200, doc);
}

void startWifi() {
  char ssid[16];
  snprintf(ssid, sizeof(ssid), "BLACKOUT_%c", nodeChar(NODE_ID));
#if defined(ESP8266)
  WiFi.persistent(false);  // do not write the hotspot settings to flash on every start
#endif
  WiFi.mode(WIFI_AP);
  // Open network on purpose: anyone nearby must be able to join. A and C sit on different channels.
  WiFi.softAP(ssid, nullptr, NODE_ID == 1 ? 1 : NODE_ID == HQ_ID ? 6 : 11, 0, 8);
  dns.start(53, "*", WiFi.softAPIP());  // every name leads here, so phones open the page by themselves

  server.on("/", HTTP_GET, [] { server.send_P(200, "text/html; charset=utf-8", PAGE); });
  server.on("/api/send", HTTP_POST, apiSend);
  server.on("/api/messages", HTTP_GET, apiMessages);
  server.on(UriBraces("/api/messages/{}"), HTTP_GET, apiMessageById);
  server.on(UriBraces("/api/tickets/{}/ack"), HTTP_POST, apiTicketAck);
  server.on("/api/status", HTTP_GET, apiStatus);
  server.on("/api/nodes", HTTP_GET, apiNodes);
  server.on("/api/mode", HTTP_POST, apiMode);
  server.on("/api/log", HTTP_GET, apiLog);
  server.onNotFound([] {
    server.sendHeader("Location", "http://192.168.4.1/");
    server.send(302, "text/plain", "");
  });
  server.begin();
  logf("WIFI hotspot %s at http://%s/", ssid, WiFi.softAPIP().toString().c_str());
}

// ---------------------------------------------------------------- boot
// Checks the packet code on every start; the result is the first line on the serial monitor.
void selfTest() {
  Packet a = {};
  a.type = T_DATA; a.origin = 1; a.dest = 3; a.id = 0xDEADBEEF; a.attempt = 2; a.ttl = 3;
  a.prio = P_SOS; a.lastHop = 2; a.len = 3;
  memcpy(a.payload, "abc", 3);
  uint8_t b[HDR + MAX_PAYLOAD];
  size_t n = encode(a, b);
  Packet c;
  bool ok = n == (size_t)HDR + 3 && decode(b, n, c) && c.id == a.id && c.attempt == 2 && c.lastHop == 2 &&
            c.prio == P_SOS && !memcmp(c.payload, "abc", 3);
  ok = ok && !decode(b, n - 1, c);         // truncated
  b[2] = 0;
  ok = ok && !decode(b, n, c);             // origin that is not a node
  ok = ok && !seenBefore(a) && seenBefore(a);
  a.attempt = 3;
  ok = ok && !seenBefore(a);               // a retry must pass the duplicate filter
  int32_t la, lo;
  ok = ok && parsePos("28.749912 77.116403", la, lo) && la == 28749912 && lo == 77116403;
  ok = ok && parsePos("-33.5 -70.25\r", la, lo) && la == -33500000 && lo == -70250000;
  ok = ok && !parsePos("91 10", la, lo) && !parsePos("0 0", la, lo) && !parsePos("28.7", la, lo) &&
       !parsePos("28.7 77.1 x", la, lo);
  memset(seen, 0, sizeof(seen));
  seenAt = 0;
  Serial.println(ok ? "selftest ok" : "SELFTEST FAILED: do not trust this build");
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println();
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  pinMode(PIN_LED, OUTPUT);
  storeBegin();
  loadPosition();
  selfTest();
  randomSeed(hwRandom());
  nextId = hwRandom();  // random start: a reboot must not reuse ids the relay still remembers
  logf("BLACKOUT NET node %c (id %d)%s", nodeChar(NODE_ID), NODE_ID, NODE_ID == HQ_ID ? ", HQ" : "");
  if (BENCH_BLOCK_DIRECT) logf("BENCH TEST MODE: A and C ignore each other's direct packets");
  if (posLatE6 == NO_POS) logf("POSITION none yet: type  pos <latitude> <longitude>  in the serial monitor");
  else logf("POSITION %.6f, %.6f (%s)", posLatE6 / 1e6, posLonE6 / 1e6, posSource);

#if defined(ESP8266)
  SPI.begin();  // fixed pins: D5 SCK, D6 MISO, D7 MOSI
#else
  SPI.begin(PIN_SCK, PIN_MISO, PIN_MOSI, PIN_NSS);
#endif
  radioError = radio.begin(LORA_FREQ_MHZ, LORA_BW_KHZ, LORA_SF, LORA_CR, LORA_SYNC, LORA_TX_DBM, LORA_PREAMBLE, 0);
  if (radioError == RADIOLIB_ERR_NONE) radioError = radio.setCRC(true);
  radioOk = radioError == RADIOLIB_ERR_NONE;
  if (radioOk) {
    radio.setDio0Action(onDio0, RISING);
    radio.startReceive();
    logf("RADIO ok: SX1278 %.1f MHz, BW %.0f kHz, SF%d, CR 4/%d, CRC on, %d dBm setting", LORA_FREQ_MHZ,
         LORA_BW_KHZ, LORA_SF, LORA_CR, LORA_TX_DBM);
  } else {
    logf("RADIO FAILED code %d: check the Ra-02 wiring, its 3.3 V supply and the solder joints", radioError);
  }
  if (HAS_WIFI) startWifi();
  else WiFi.mode(WIFI_OFF);
  nextHbMs = millis() + random(1000, 5000);  // first heartbeat soon: two powered nodes see each other in seconds
}

void loop() {
  if (HAS_WIFI) {
    dns.processNextRequest();
    server.handleClient();
  }
  if (radioOk) {
    pollRadio();
    expireMessages();
    heartbeatTick();
    pumpTx();
  }
  pollButton();
  updateLed();
  serialTick();
  statusTick();
}
