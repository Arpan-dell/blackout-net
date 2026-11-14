#pragma once
#include <Arduino.h>

// The whole web interface, stored in flash and served at http://192.168.4.1/.
// Nothing in it loads from the internet: no fonts, scripts or map tiles from outside.
const char PAGE[] PROGMEM = R"HTML(<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BLACKOUT NET</title>
<style>
:root { color-scheme: light dark; --page: #f9f9f7; --card: #fcfcfb; --ink: #0b0b0b; --ink2: #52514e; --line: #c3c2b7;
  --good: #0ca30c; --warn: #fab219; --crit: #d03b3b; --blue: #2a78d6; }
@media (prefers-color-scheme: dark) { :root { --page: #0d0d0d; --card: #1a1a19; --ink: #f0efec; --ink2: #c3c2b7;
  --line: #383835; --blue: #3987e5; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink); font: 16px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 640px; margin: 0 auto; padding: 12px; }
h1 { font-size: 20px; margin: 0; letter-spacing: .04em; }
h2 { font-size: 15px; margin: 0 0 8px; color: var(--ink2); }
.offline { color: var(--ink2); font-size: 13px; margin: 2px 0 10px; }
#link { padding: 8px 12px; border-radius: 10px; border: 2px solid var(--crit); font-weight: 600; margin-bottom: 10px; display: none; }
nav { display: flex; gap: 8px; margin-bottom: 12px; }
button, input, select { font: inherit; color: var(--ink); }
button { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 10px 14px; min-height: 44px; cursor: pointer; }
button[aria-pressed="true"], nav button[aria-current="page"] { background: var(--ink); color: var(--card); border-color: var(--ink); }
:focus-visible { outline: 3px solid var(--blue); outline-offset: 2px; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 14px; margin-bottom: 12px; }
label, legend { display: block; font-weight: 600; margin: 12px 0 4px; padding: 0; }
fieldset { border: 0; padding: 0; margin: 0; }
.choices { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px; }
.choices label { margin: 0; font-weight: 400; border: 1px solid var(--line); border-radius: 10px; padding: 10px; min-height: 44px; cursor: pointer; }
.choices label:has(input:checked) { border: 2px solid var(--ink); font-weight: 600; }
input[type=text] { width: 100%; padding: 10px; border: 1px solid var(--line); border-radius: 10px; background: var(--page); min-height: 44px; }
.hint { color: var(--ink2); font-size: 13px; }
#send, #sos-now { width: 100%; margin-top: 14px; background: var(--crit); border-color: var(--crit); color: #fff; font-weight: 700; font-size: 18px; }
#say { font-weight: 600; margin-top: 10px; min-height: 1.45em; }
ul { list-style: none; margin: 0; padding: 0; }
li.item { border-top: 1px solid var(--line); padding: 10px 0; }
.tag { display: inline-block; border: 1px solid var(--line); border-radius: 999px; padding: 1px 10px; font-size: 13px; font-weight: 700; margin-right: 6px; }
.tag.sos { border-color: var(--crit); }
.good { color: var(--good); } .warn { color: var(--warn); } .crit { color: var(--crit); }
dl { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 12px; margin: 0; }
dt { color: var(--ink2); font-size: 13px; } dd { margin: 0; font-weight: 600; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { text-align: left; padding: 6px 4px; border-top: 1px solid var(--line); }
pre { font-size: 12px; overflow: auto; max-height: 320px; margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
[hidden] { display: none !important; }
</style>
</head>
<body>
<main>
  <h1>BLACKOUT NET <span id="who"></span></h1>
  <p class="offline">Local network only. No internet is needed or used. Stay connected to this Wi-Fi.</p>
  <div id="link" role="alert"></div>

  <div class="card" id="locked" hidden>
    <h2>Coordinators only</h2>
    <p class="hint">The inbox, everyone's messages and the settings need the coordinator PIN.</p>
    <input type="password" id="pin-in" inputmode="numeric" autocomplete="off" aria-label="Coordinator PIN" placeholder="PIN">
    <button id="pin-go" type="button">Unlock</button> <span id="pin-say" class="hint" role="status"></span>
  </div>

  <nav aria-label="Sections">
    <button id="tab-send" hidden>Send</button>
    <button id="tab-inbox" hidden>HQ inbox</button>
    <button id="tab-net">Network</button>
  </nav>

  <section id="view-send" hidden>
    <div class="card">
      <button id="sos-now" type="button">SOS: send now</button>
      <p class="hint">One tap sends an SOS with this node's location. Add details below if you can.</p>
      <div id="say-sos" role="status"></div>
    </div>
    <form class="card" id="form">
      <h2>Ask the local coordinators for help</h2>
      <p class="hint">This reaches the coordinators at the HQ node. It does not call the emergency services.</p>
      <fieldset><legend>What do you need?</legend><div class="choices" id="cats"></div></fieldset>
      <fieldset><legend>How urgent?</legend><div class="choices">
        <label><input type="radio" name="type" value="SOS" checked> SOS, urgent</label>
        <label><input type="radio" name="type" value="NORMAL"> Normal</label>
      </div></fieldset>
      <label for="text">Short message (optional)</label>
      <input type="text" id="text" name="text" autocomplete="off" placeholder="Example: 2 people, one injured">
      <label for="landmark">Where are you? (optional: landmark or zone)</label>
      <input type="text" id="landmark" name="landmark" autocomplete="off" placeholder="Example: Hostel B gate">
      <p class="hint">The HQ sees where this node stands and roughly how far your phone is from it. A landmark helps the team find you.</p>
      <div class="hint" id="count"></div>
      <button id="send" type="submit">Send</button>
      <div id="say" role="status"></div>
    </form>
    <div class="card">
      <h2>Your messages from this phone</h2>
      <ul id="mine"></ul>
    </div>
  </section>

  <section id="view-inbox" hidden>
    <div class="card">
      <h2>Requests received</h2>
      <p class="hint">"Acknowledge" marks a request as seen on this screen. The sender's phone already shows it as delivered.</p>
      <ul id="tickets"></ul>
    </div>
  </section>

  <section id="view-net" hidden>
    <div class="card"><h2>This node</h2><dl id="facts"></dl></div>
    <div class="card">
      <h2>Scheduling</h2>
      <button id="prio" aria-pressed="true">SOS first: on</button>
      <p class="hint">Turn off to send strictly in arrival order (FIFO) when measuring what priority gains.</p>
    </div>
    <div class="card"><h2>Other nodes heard</h2>
      <table><thead><tr><th>Node</th><th>Last heard</th><th>Route</th><th>RSSI</th><th>SNR</th></tr></thead><tbody id="peers"></tbody></table>
    </div>
    <div class="card"><h2>Radio log</h2><pre id="log"></pre></div>
  </section>
</main>

<script>
const $ = id => document.getElementById(id);
const el = (tag, props, ...kids) => { const e = Object.assign(document.createElement(tag), props); e.append(...kids); return e; };
const CATS = { medical: "Medical", fire: "Fire", trapped: "Trapped", supplies: "Food / water", security: "Security", other: "Other" };
const bytes = s => new TextEncoder().encode(s).length;
const secs = ms => ms < 60000 ? Math.round(ms / 1000) + " s" : Math.floor(ms / 60000) + " min";
let st = null, tab = null, room = 38, mine = [], drawn = {};
try { mine = JSON.parse(localStorage.getItem("mine") || "[]"); } catch (e) {}
const firstSeen = new Map();  // message id -> clock time it arrived, worked out once

let pin = "", coordinator = false;
try { pin = localStorage.getItem("pin") || ""; } catch (e) {}
function setPin(v) { pin = v; try { localStorage.setItem("pin", v); } catch (e) {} }
async function api(path, opt) {
  const url = pin ? path + (path.includes("?") ? "&" : "?") + "pin=" + encodeURIComponent(pin) : path;
  const r = await fetch(url, opt), j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || "HTTP " + r.status);
  return j;
}
function show(name) {
  tab = name;
  for (const t of ["send", "inbox", "net"]) {
    $("view-" + t).hidden = t !== name;
    if (t === name) $("tab-" + t).setAttribute("aria-current", "page"); else $("tab-" + t).removeAttribute("aria-current");
  }
}
for (const t of ["send", "inbox", "net"]) $("tab-" + t).onclick = () => { show(t); poll(); };

for (const [value, label] of Object.entries(CATS))
  $("cats").append(el("label", {}, el("input", { type: "radio", name: "category", value, checked: value === "medical" }), " " + label));

function count() {
  const used = bytes($("text").value.trim()) + bytes($("landmark").value.trim());
  $("count").textContent = `${used} of ${room} bytes used by message and landmark` + (used > room ? ". Too long: shorten one of them." : ".");
  $("count").className = used > room ? "hint crit" : "hint";
  return used <= room;
}
$("text").oninput = $("landmark").oninput = count;

async function send(body, say) {
  try {
    const r = await api("/api/send", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    mine.push(r.message_id);
    try { localStorage.setItem("mine", JSON.stringify(mine.slice(-40))); } catch (e) {}
    say.textContent = "Queued. It is delivered only when the status below says DELIVERED.";
    poll();
    return true;
  } catch (err) { say.textContent = "Not sent: " + err.message; return false; }
}
// No confirm() pop-up: the Wi-Fi sign-in window phones open often blocks pop-ups, which silently stopped the SOS.
$("sos-now").onclick = async () => {
  const b = $("sos-now");
  b.disabled = true;  // one tap is enough; a second tap within 5 s would only queue a duplicate
  await send({ destination: "HQ", type: "SOS", category: "other", text: "", landmark: "" }, $("say-sos"));
  setTimeout(() => { b.disabled = false; }, 5000);
};
$("form").onsubmit = async e => {
  e.preventDefault();
  const f = new FormData(e.target);
  if (!count()) return $("say").textContent = "Too long: shorten the message or the landmark.";
  const body = { destination: "HQ", type: f.get("type"), category: f.get("category"),
                 text: f.get("text").trim(), landmark: f.get("landmark").trim() };
  if (await send(body, $("say"))) { $("text").value = ""; count(); }
};

function statusOf(m) {
  if (m.status === "delivered") return ["good", "✓ DELIVERED", `HQ confirmed it in ${(m.latency_ms / 1000).toFixed(1)} s on try ${m.tries}` +
    (m.ack_via === st.hq ? ", directly." : `, relayed by node ${m.ack_via}.`)];
  if (m.status === "expired") return ["crit", "✕ NOT DELIVERED", `No confirmation from HQ after ${m.tries} tries. Send it again.`];
  if (m.status === "waiting_ack") return ["warn", "… WAITING FOR HQ", `Sent ${m.tries} of ${m.max_tries} times, no confirmation yet.`];
  if (m.status === "transmitting") return ["warn", "… SENDING", "On the air now."];
  return ["warn", "… QUEUED", "Waiting for its turn on the radio."];
}
function head(m) {
  return el("div", {}, el("span", { className: "tag" + (m.type === "SOS" ? " sos" : "") }, m.type === "SOS" ? "SOS" : "Normal"),
            el("strong", {}, CATS[m.category] || m.category), m.text ? " · " + m.text : "", m.landmark ? " · at " + m.landmark : "");
}
// Rebuild a list only when its content changed, so a focused button is not replaced under the user.
function redraw(id, key, build) {
  if (drawn[id] === key) return;
  drawn[id] = key;
  const items = build();
  $(id).replaceChildren(...(items.length ? items : [el("li", { className: "hint" }, "Nothing yet.")]));
}
function drawMine(outbox) {
  const list = outbox.filter(m => mine.includes(m.message_id)).reverse();
  redraw("mine", JSON.stringify(list.map(m => [m.message_id, m.status, m.tries])), () => list.map(m => {
    const [cls, label, detail] = statusOf(m);
    return el("li", { className: "item" }, head(m), el("div", {}, el("strong", { className: cls }, label), " " + detail),
              el("div", { className: "hint" }, "Message id " + m.message_id));
  }));
}
function drawTickets(inbox) {
  for (const t of inbox) if (!firstSeen.has(t.message_id)) firstSeen.set(t.message_id, new Date(Date.now() - t.age_ms));
  const list = inbox.slice().sort((a, b) => a.acknowledged - b.acknowledged || (b.type === "SOS") - (a.type === "SOS") || a.age_ms - b.age_ms);
  redraw("tickets", JSON.stringify(list.map(t => [t.message_id, t.acknowledged])), () => list.map(t => {
    const ack = t.acknowledged ? el("div", { className: "hint" }, "✓ Acknowledged by coordinator")
      : el("button", { onclick: async () => { await api(`/api/tickets/${t.message_id}/ack`, { method: "POST" }).catch(() => {}); poll(); } }, "Acknowledge");
    return el("li", { className: "item" }, head(t),
      el("div", { className: "hint" }, `From node ${t.origin} at ${firstSeen.get(t.message_id).toLocaleTimeString()} · ` +
        (t.via === t.origin ? "received directly" : "relayed by node " + t.via) + ` · RSSI ${t.rssi} dBm, SNR ${t.snr} dB · id ${t.message_id}`), ack);
  }));
}
function drawNet(nodes, log) {
  const c = st.counters, r = st.radio, pct = st.delivery_pct == null ? "no finished messages yet" : st.delivery_pct.toFixed(0) + " %";
  const rows = [["Node", `${st.node} (${st.role})`], ["Uptime", secs(st.uptime_s * 1000)],
    ["Radio", r.ok ? `${r.chip} ok` : `FAILED, code ${r.error_code}`], ["Radio settings", `${r.freq_mhz} MHz, BW ${r.bw_khz} kHz, SF${r.sf}, CR 4/${r.cr}, ${r.tx_dbm_setting} dBm setting`],
    ["Last packet", r.last_rssi == null ? "none yet" : `RSSI ${r.last_rssi} dBm, SNR ${r.last_snr} dB`], ["Devices on this Wi-Fi", st.wifi_clients],
    ["Sent / received / relayed", `${c.sent} / ${c.received} / ${c.relayed}`], ["Waiting: queued / for ACK / relay", `${st.queues.queued} / ${st.queues.waiting_ack} / ${st.queues.relay}`],
    ["Retries", c.retries], ["Delivered / expired", `${c.delivered} / ${c.expired} (${pct})`],
    ["Duplicates / CRC errors / bad", `${c.duplicates} / ${c.crc_errors} / ${c.bad_packets}`],
    ["Airtime in the last hour", `${(st.airtime_ms_last_hour / 1000).toFixed(1)} s of ${st.airtime_budget_ms / 1000} s allowed`]];
  if (st.bench_block_direct) rows.push(["Bench test mode", "ON: A and C ignore each other's direct packets"]);
  $("facts").replaceChildren(...rows.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, String(v))]));
  $("prio").setAttribute("aria-pressed", st.priority);
  $("prio").textContent = "SOS first: " + (st.priority ? "on" : "off (FIFO)");
  $("peers").replaceChildren(...nodes.nodes.map(n => el("tr", {}, el("td", {}, n.name),
    el("td", {}, secs(n.age_ms) + " ago" + (n.age_ms > 3000 * nodes.hb_interval_s ? " · OFFLINE" : "")),
    el("td", {}, n.via === n.name ? "direct" : "via " + n.via), el("td", {}, n.rssi + " dBm"), el("td", {}, n.snr + " dB"))));
  if (!nodes.nodes.length) $("peers").append(el("tr", {}, el("td", { colSpan: 5, className: "hint" }, "No other node heard yet.")));
  $("log").textContent = log.lines.join("\n");
}
$("prio").onclick = async () => { await api("/api/mode?priority=" + (st.priority ? 0 : 1), { method: "POST" }).catch(() => {}); poll(); };

async function poll() {
  try {
    st = await api("/api/status");
    room = st.text_room_bytes;
    const isHq = st.role === "hq";
    $("who").textContent = "· Node " + st.node + (isHq ? " (HQ)" : "");
    $("tab-send").hidden = false;  // phones can send through any node, the HQ too
    $("tab-inbox").hidden = !isHq;
    if (!tab) { show("send"); count(); }
    const msgs = await api("/api/messages");
    if (pin && !msgs.coordinator) { setPin(""); $("pin-say").textContent = "Wrong PIN."; }  // stop resending a wrong one
    coordinator = msgs.coordinator;
    if (coordinator && $("pin-say").textContent === "Checking...") $("pin-say").textContent = "Unlocked.";
    $("locked").hidden = coordinator || tab === "send" || !tab;
    drawMine(msgs.outbox);
    drawTickets(msgs.inbox);
    if (tab === "net") drawNet(await api("/api/nodes"), await api("/api/log"));
    $("link").style.display = st.radio.ok ? "none" : "block";
    $("link").textContent = "✕ This node's radio did not start. Messages cannot be sent. Tell the team.";
  } catch (e) {
    $("link").style.display = "block";
    $("link").textContent = "✕ Lost contact with the node. Check that this phone is still on the BLACKOUT Wi-Fi.";
  }
}
$("pin-go").onclick = () => { setPin($("pin-in").value.trim()); $("pin-in").value = ""; $("pin-say").textContent = "Checking..."; poll(); };
poll();
setInterval(poll, 1500);
</script>
</body>
</html>
)HTML";
