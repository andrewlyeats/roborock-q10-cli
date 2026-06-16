# Roborock Q10 (B01) — protocol notes + a working CLI

![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![status: unofficial](https://img.shields.io/badge/status-unofficial-orange.svg)

Notes from reverse-engineering how the Roborock Q10 S5+ talks to Roborock's cloud — with a CLI
(`vac.py`) as proof it works. The Q10 S5+ is a **"B01" device: cloud-only**, with no local-network
control path; every command is relayed through Roborock's MQTT broker (or its REST API).

**Just want to use your vacuum?** The [Home Assistant Roborock integration][ha] probably already
covers it with a GUI. This repo is for people who want to **understand or extend the B01 protocol**,
or drive the vacuum from a terminal / cron / their own scripts.

**Status:** a personal project, shared as-is. Unofficial, no warranty, no support promised — see the
disclaimer below.

### What this documents (the part worth reading)

- **The B01 map format** — the room grid is LZ4-compressed; path/position arrive as protocol-301
  frames. Decoded end-to-end into a labeled floor plan — grid dimensions read from the frame header,
  and the path↔grid registration auto-fit per map (the origin isn't transmitted in the stream).
  → [DESIGN_NOTES.md](DESIGN_NOTES.md), [`decode_map.py`](decode_map.py)
- **The cloud write path** — room-clean and schedule writes go through a REST `/jobs` call that needs
  **Hawk *body* signing**; getting that wrong looks exactly like "writes don't work / token scope,"
  but it isn't. → [DESIGN_NOTES.md](DESIGN_NOTES.md)
- **A single-connection daemon** — one held MQTT connection serving every command, to stay under the
  account-level `135` rate-limit that otherwise locks out the CLI *and* the app. → [DESIGN_NOTES.md](DESIGN_NOTES.md)
- **The B01 data-point dictionary** — what each data-point means and how its payload decodes (the
  robot emits ~44; only ~19 are modeled in `status`). → [DP_DICTIONARY.md](DP_DICTIONARY.md)

What's been verified vs. still open is scoped in [CAPABILITIES.md](CAPABILITIES.md) (can / can't /
unknown) and [ROADMAP.md](ROADMAP.md).

## ⚠️ Disclaimer

This is an **unofficial**, community reverse-engineered tool — **not affiliated with, endorsed by, or
supported by Roborock**. It talks to your own account over Roborock's cloud and relies on undocumented
internals the vendor can change at any time. Provided **as-is, no warranty, use at your own risk.**
Commands are reversible and the project errs toward safety (e.g. `clean-rooms --dry-run` posts a
*disabled* job), but you are responsible for your device and account — don't run it on hardware or an
account you can't afford to disrupt.

## Tested hardware

| Item | Tested |
|---|---|
| Model | Roborock Q10 S5+ (`roborock.vacuum.ss07`, B01 protocol) |
| Firmware | **last validated against 03.11.24** (2026-06) |
| Python | 3.11 (3.11+ required) · `python-roborock` 5.14.x |

Other Roborock models are **untested** — they may share the B01 protocol (in which case much of this
should work) or differ. Reports from other models are welcome ([CONTRIBUTING.md](CONTRIBUTING.md)).
Firmware updates can drift from what's documented here.

## Setup

Needs Python **≥3.11** and the deps in `requirements.txt` (python-roborock, lz4, Pillow):
`pip install -r requirements.txt` (or `requirements.lock.txt` for the exact known-good pins).

> **The one install gotcha:** python-roborock 5.x requires Python ≥3.11. On 3.9/3.10 (e.g. macOS
> system `python3`) `pip` silently installs an old 0.x that lacks the B01 device modules — which looks
> like "the library is broken." Run `vac.py` on a ≥3.11 interpreter that has the deps.

First-time auth (one time):

```bash
./vac.py login --email you@example.com   # emails you a 6-digit code
./vac.py discover                        # fetches + caches your device list
```

`login` saves a token to `~/.roborock_vac.json` (gitignored; schema in
[`credentials.example.json`](credentials.example.json)); `discover` caches device/home data to
`~/.roborock_vac_cache.pkl` so later calls don't re-hit the cloud.

> **Be gentle with the cloud.** Many separate MQTT connections in a short window trip an account-level
> rate-limit (`code 135`) that locks out the CLI *and* the app for a while. The **daemon** (below)
> holds a single connection so this can't happen — it's the recommended way to use this tool.

## Daemon

A small background daemon holds **one** persistent cloud connection and serves every command over a
local socket, so commands don't each reconnect (and can't trip `135`). When one is running it's the
default path; if it isn't, commands print how to start it. It's **validated live** — one held
connection served reads, taps, and an hour of cleans without reconnecting. (Mechanics — escalating
backoff, the `--careful` halt-file, automatic `135` recovery status — are in
[DESIGN_NOTES.md](DESIGN_NOTES.md).)

```bash
./vac.py daemon start --careful   # recommended: holds one connection, stops on the first 135/auth complaint
./vac.py daemon status            # device, health, last update, taps
./vac.py daemon stop
./vac.py daemon restart           # e.g. after `pip install -U python-roborock`
./vac.py status --force           # run ONE command standalone (own session; avoid repeating)
```

**Telemetry taps** (the daemon sees the whole stream, so capture lives there — opt-in, off by default):

```bash
./vac.py daemon record --events ev.jsonl    # every decoded data-point
./vac.py daemon record --novel new.jsonl    # first-seen DP names (catch new behaviors)
./vac.py daemon record --bytes raw.jsonl     # raw frames (incl. binary/map)
./vac.py daemon record --off
```

## Usage

Everyday commands:

```bash
./vac.py status        # battery, state, fan, water, mode, clean time/area  (+--json)
./vac.py start | pause | resume | stop | dock | dock-empty | find
./vac.py rooms                       # list rooms on the current map (id + name)
./vac.py clean-rooms kitchen study   # clean only those rooms (full cycle; +--fan/--water/--route/--count)

./vac.py fan turbo               # quiet | balanced | turbo | max | max_plus
./vac.py water high              # off | low | medium | high
./vac.py mode vac_and_mop        # vac_and_mop | vacuum | mop
./vac.py consumables             # brush/filter/sensor life counters  (+--json)
./vac.py dnd on --start 22:00 --end 08:00   # also: dnd off

# Cloud schedules (stored server-side via the REST API):
./vac.py schedule list                                       # id · time · rooms · fan/water
./vac.py schedule add --time 09:00 --days mon,wed,fri --rooms kitchen study
./vac.py schedule enable|disable|delete <id>
```

Capture & decode (the reverse-engineering surface):

```bash
./vac.py watch                           # live table of the modeled status fields  (--out clean.csv for CSV)
./vac.py watch --raw --out clean.jsonl   # EVERY decoded data-point, one JSON object per line
./vac.py map                             # render the labeled floor plan -> map_rooms.png (+ map_path.svg if cleaning)
./vac.py watch --bytes --out cap.jsonl && ./decode_map.py cap.jsonl   # low-level: byte capture -> offline decode
./vac.py history --from-capture clean.jsonl   # decode the per-clean back-catalog from a capture
./vac.py raw STATUS                       # send any raw B01 data-point (run `raw BADNAME` to list them)
```

Multiple robots? Add `--device <duid>` (DUIDs via `./vac.py discover`). Most B01 commands are
fire-and-forget (no response body); `raw` is the escape hatch for features without a dedicated command.

## Files

| Path | Purpose |
|---|---|
| `vac.py` | The CLI |
| `decode_map.py` | Decode the live map/path (incl. grid georeference) from a `watch --bytes` capture |
| `check_roborock_api.py` | Canary: verify the `python-roborock` internals this tool relies on are still present (run after upgrades) |
| `clean.csv` | Example `watch --out` output (one mopping run; benign telemetry, no PII) |
| [CAPABILITIES.md](CAPABILITIES.md) | Every interaction, scoped: can / can't / unknown |
| [DP_DICTIONARY.md](DP_DICTIONARY.md) | What each data-point means + decoded formats |
| [DESIGN_NOTES.md](DESIGN_NOTES.md) | Why it works this way + the reverse-engineering findings |
| [ROADMAP.md](ROADMAP.md) | What works, what's planned, known limitations |
| `credentials.example.json` | Schema of the login file `login` writes to `~/.roborock_vac.json` |
| `~/.roborock_vac.json` · `~/.roborock_vac_cache.pkl` | Login token · cached home-data (gitignored) |

## Known limitations

- **Cloud-only.** No local control for this model (B01 protocol).
- **Map.** `vac.py map` renders the room grid (colour-coded, room-name-labeled). The grid streams
  even while docked; the cleaning path + live position only stream *during* a clean. Georeference:
  grid dimensions come from the frame header, and the path↔grid origin (not transmitted in the stream)
  is auto-fit per capture → `map_overlay.png`. Obstacles are cloud-only (not in this data) — the
  library exposes none of this natively.
- **Room cleaning** (`clean-rooms`) issues a one-time REST `/jobs` clean for the named rooms;
  `--dry-run` posts an inert *disabled* job. A complete cycle (undock → clean → dock → charging) is
  validated live. The job fires **~2 min later** (scheduled, not instant). See [DESIGN_NOTES.md](DESIGN_NOTES.md).
- **Structured map mutations are read-only** — virtual walls, no-go/no-mop zones, room
  split/merge/rename decode but can't be set from here.
- **Some settings are cloud-authoritative** (volume / child-lock / boost / DND) — writes may revert;
  change those in the app. Runtime settings (fan/water/mode) persist.
- **Consumables** show hours used + % remaining (confirmed against the app: main 300 h / side 200 h /
  filter 150 h).

## Built on / related projects

An unofficial CLI + daemon built on others' work — full credits in [CREDITS.md](CREDITS.md):

- [python-roborock][pr] — the library this depends on.
- [Home Assistant Roborock integration][ha] — the single-connection coordinator pattern the daemon follows.
- [local_roborock_server](https://github.com/Python-roborock/local_roborock_server) /
  [Valetudo](https://github.com/Hypfer/Valetudo) — if you want a full *local* cloud replacement instead.
- [XiaomiRobotVacuumProtocol](https://github.com/marcelrv/XiaomiRobotVacuumProtocol),
  [dustcloud](https://github.com/dgiese/dustcloud) — the protocol-RE lineage.

## Contributing & license

Contributions — especially reports from other Roborock models — are welcome
([CONTRIBUTING.md](CONTRIBUTING.md)). Before testing against a live robot, read the **Be gentle with
the cloud** note above and [DESIGN_NOTES.md](DESIGN_NOTES.md). Licensed under the [MIT License](LICENSE).

## Built with AI assistance

Developed with AI coding assistants (Anthropic's Claude Opus 4.8 and Claude Sonnet 4.6) under human
direction — code, reverse-engineering, and docs. A human reviewed the work and ran every live test
against the real device. See [CREDITS.md](CREDITS.md).

[ha]: https://www.home-assistant.io/integrations/roborock/
[pr]: https://github.com/Python-roborock/python-roborock
