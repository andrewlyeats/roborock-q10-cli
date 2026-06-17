# Roadmap

## Status

This is a standalone Python CLI for controlling a Roborock Q10 (B01-series) robot vacuum
over Roborock's cloud. The core CLI is implemented and validated against a live device:
read device status, list cloud schedules, run room-targeted cleans, decode and render the
robot's map, and stream live telemetry. It talks to the vacuum through Roborock's cloud
MQTT/REST APIs (there is no local control on B01 hardware).

**Where this sits relative to upstream (read before treating any feature as unique).** Basic
control/status/sensors are already in `python-roborock` + Home Assistant core, and map/georef/
wall-zone decode is **converging in open python-roborock PRs** (#847 map, #848 georef, #850 walls,
#851 MQTT room-clean). Several "Working today" items below therefore overlap with fast-moving
upstream work — treat them as an independent, dated corroboration, not a sole source. The durable,
least-duplicated contributions are the **dated, confidence-tagged protocol reference**
([PROTOCOL.md](PROTOCOL.md)) and the **REST `/jobs` Hawk *body*-signing** finding (filed upstream as
our own issue #849, unmerged). The intent is to upstream the differentiated pieces, not to compete
on the CLI.

## Working today

These capabilities are implemented and validated against a live device:

- **Status & consumables** — current state, battery, fan/water/mode, clean progress and
  area, plus consumable wear (filter/brushes) as hours used and percent remaining.
- **Schedules** — list cloud schedules with their cron, target rooms, and fan/water levels.
  Add/enable/disable/delete are implemented (REST writes work).
- **Room listing** — read the map's room directory (ids and names).
- **Room-targeted cleaning** — `clean-rooms <name|id>…` starts a clean of specific rooms via
  a one-time REST job, with per-job fan/water/route options. Room targeting is confirmed
  correct on the wire across supervised live runs.
- **Map decode & render** — decode the robot's streamed map into a colour-coded, room-labeled
  floor plan and a cleaning-path overlay (georeferenced). Works while docked for the floor
  plan; live robot position is available during an active clean.
- **Structured map/position output** — `decode_map.py --json` emits the decode as data (rooms with
  pixel bbox/centroid, robot position + derived current room, the path, and the georeference
  transform; schema `roborock-b01-map/1`) so a status panel / web UI / Home Assistant shell command
  can consume it without parsing a PNG. Plus `datapoints.json`, a machine-readable index of all 114
  data-points + value enums. *(We provide the data; you build the view.)*
- **Live telemetry stream** — `watch` follows the device in real time (optional CSV/JSONL
  output) and projects a clean ETA and battery-to-finish estimate.
- **Scalar settings** — set runtime parameters like fan, water, and clean mode.
- **Single-connection daemon** — a long-running helper holds one cloud connection and serves all CLI
  commands over a local socket (no reconnect per command). Validated against a live robot: one held
  connection served an hour of cleans without reconnecting, and `--careful` mode survives `restart`.
- **Room-targeted cleaning, end to end** — a complete clean cycle (undock → clean → dock → charging) is
  validated live, including `--water` / `--route` / `--count` taking effect on the wire.
- **Clean history** — decode the robot's per-clean records (date, duration, area, water, mode, route,
  passes, completed) with `history --from-capture` from a `watch`/`daemon record` capture.

## Planned / not yet validated

- **A *strictly* fault-free complete clean** — a complete cycle works, but no run has been clean. Two
  distinct failure modes have shown up: (1) a **transient cliff-sensor fault (501) at a fixed doorway
  threshold** that the robot self-clears in seconds and finishes the clean (environmental), and (2) on at
  least one run the robot **got trapped on the return and needed a manual reset** (it did *not* self-recover).
  A run over a cleared/zoned sill, completing untouched, is the remaining confirmation.
- **Live `history` fetch** — the back-catalog decodes offline from a capture today; a *live* pull is
  app/push-only (the robot broadcasts its history to the app, not to a direct request) — still WIP.
- **Automatic `135` recovery** — the daemon's cool-down/reconnect path is offline-tested but not yet
  exercised by a natural live ban.
- **Optional package split** — packaging the CLI and the map decoder for easier install.
- **Home Assistant usage section** — optional docs for driving the CLI from HA shell commands.
- **Other B01 / Q-series models** — only the Q10 is tested today. Support for sibling models
  is plausible but unverified; community testing and contributions are welcome.

## Known limitations

- **Cloud-only.** B01 hardware offers no documented local API, so all control goes through
  Roborock's cloud MQTT/REST. There is no offline/LAN mode.
- **One tested device.** Everything here is validated on a single Roborock Q10 (S5+). Behaviour
  on other firmware or models may differ.
- **Depends on `python-roborock` internals.** The CLI uses private, undocumented internals of
  the `python-roborock` library, which can break on upgrade. This is mitigated by a pinned,
  known-good dependency set and a small canary script that flags an internal that moved.
- **Some settings are cloud-authoritative.** Volume, child-lock, boost, and do-not-disturb are
  re-asserted by the server, so writes to them may revert. Runtime settings (fan/water/mode)
  stick.
- **Connection rate limits.** Reconnecting too frequently can trip an account-level connection
  limit (`code 135`). Be gentle, and prefer the long-running daemon (validated) over rapid
  repeated one-shot commands.
- **Structured map mutations are read-only.** Virtual walls, no-go/no-mop zones, and room
  split/merge/rename can be decoded but not set from this tool.
