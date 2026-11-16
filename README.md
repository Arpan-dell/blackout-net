# BLACKOUT NET

Offline emergency messaging for places where the mobile network and internet are down. A person near a
node joins its Wi-Fi with an ordinary phone (no app, no SIM data), types a short request, and it travels
over 433 MHz LoRa radio from node to node to the coordinators' HQ. The sender's phone shows DELIVERED only
after the HQ's confirmation has come back.

```
Phone ─Wi-Fi─> Node A ─LoRa─> Node B (relay) ─LoRa─> Node C (HQ) ─Wi-Fi─> Coordinator's phone
                 <──────────────── confirmation C → B → A ────────────────
```

Each node is an ESP32 DevKit V1 with an Ai-Thinker Ra-02 (SX1278) radio. Built for the VIHAAN X hardware
hackathon.

## What's in this repository

| Folder or file | What it is |
|---|---|
| [firmware/](firmware/) | **Phase 1**: the working system. Flash and test this first. Its README has the flashing steps, tests and troubleshooting. |
| [firmware-phase2/](firmware-phase2/) | **Phase 2**: phase 1 plus adaptive spreading factor (the network speeds up when links are strong and slows down when they are weak). Use it once phase 1 works. |
| [tools/monitor.py](tools/monitor.py) | Laptop dashboard: which nodes are alive, their signal, every heartbeat, a map. `python tools/monitor.py --mock` runs without hardware. |
| [tools/priority_test.py](tools/priority_test.py) | Measures how much faster SOS messages get through than normal ones under load. |
| [tools/adaptive_test.py](tools/adaptive_test.py) | Phase 2: measures adaptive SF against the fixed setting. |
| [tools/control_room.py](tools/control_room.py) | **Control room**: map of every node, every message with where the sender is, the gimbal drone's live camera from the GCS with its controls (pan, tilt, zoom, focus, aim, photo, record), and "Send scout here". `--mock` runs without hardware. |
| [tools/control_room.bat](tools/control_room.bat) | Double-click start for the control room: finds node C on USB, camera straight from the Jetson. |
| [tools/hq_forward.py](tools/hq_forward.py) | Runs on the gimbal drone's companion computer: passes node C's USB output to the control room over the drones' Wi-Fi. |
| [tools/relay_compare.py](tools/relay_compare.py) | Drones: compares signal and delivery with node B on the ground and on the relay drone. |
| [tools/city_plan.py](tools/city_plan.py) | Delhi-wide showcase: a node at every site (flag masts), hops to the nearest HQ, drawn on a map. |
| [plan.md](plan.md) | Flowcharts and the complete procedure, from parts to demonstration, with the current status. |
| [decision.md](decision.md) | Every design choice, what else was considered, and why. |

## Quick start

1. Wire three nodes as in plan.md (section 5.2). Attach the antennas before powering on.
2. Install VS Code with the PlatformIO extension and open the `firmware` folder.
3. Flash each board with its role: `pio run -e node_a -t upload`, then `node_b`, then `node_c`.
4. Join the `BLACKOUT_A` Wi-Fi with a phone. The page opens by itself (or go to http://192.168.4.1).
5. Send a message; watch it arrive on a second phone joined to `BLACKOUT_C`.

## Features

- Phone page served by the node itself, with no internet and no app: one-tap categories, SOS or normal,
  live delivery status.
- HQ inbox with SOS first and an Acknowledge button for the coordinator.
- Real end-to-end confirmation, retries with a clear "not delivered" at the end, never a false "delivered".
- Relay with duplicate filtering and a hop limit; adding a fourth node needs no code change.
- SOS messages sent before normal ones, switchable to plain first-in-first-out for measurement.
- Physical SOS button and status LED on each node.
- Heartbeats from every node, shown on the phone's Network tab and on the laptop dashboard.
- Air time kept under 10 % per hour; conservative transmit power.
- Phase 2: adaptive spreading factor chosen from measured signal quality.
- Drones: node B flies on a relay drone 30–50 m up; node C, the HQ, rides on the gimbal-camera drone.
- Control room: live map of all nodes (moving with their drones), every SOS with a search circle around the
  sender, the gimbal camera's live video, and a confirmed "Send scout here" that flies the drone there
  through the team's GCS. The sender's internet is never used.
- Mission planner: for each SOS, a full virtual drone mission (relays needed, routes, heights, timings,
  battery) played on the real map with ARM, before any drone flies.
- Drone plan: the control room works out where each relay drone must hover to keep the mesh, checks that
  the gimbal drone stays in reach of the mesh all the way to the sender, and flies each one on a click.
- Positions: typed in once over USB for ground nodes; nodes on drones use the drone's own GPS.
- City plan: what a node at every flag mast across Delhi would look like. See plan.md, section 4c.

## Status

The software is written and compiles; it has **not yet run on the real boards**. See the status table in
[plan.md](plan.md) for what has been tested and what is still to do, and the known limits listed there.

Range: tested at 1.5 km between each node.

Designed and developed by [Arpan Ailawadi](https://www.linkedin.com/in/arpan-ailawadi/)
