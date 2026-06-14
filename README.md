# Roborock Q10 S5+ CLI

![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![status: unofficial](https://img.shields.io/badge/status-unofficial-orange.svg)

A small CLI (`vac.py`) for controlling a Roborock Q10 S5+ from the command line,
built on [python-roborock](https://github.com/Python-roborock/python-roborock).

> **Heads-up:** the Q10 S5+ is a "B01" device and is **cloud-only** — there is no
> local-network control path for this model. Every command is relayed through
> Roborock's MQTT broker. See [DESIGN_NOTES.md](DESIGN_NOTES.md) for the details.

## ⚠️ Disclaimer

This is an **unofficial**, community reverse-engineered tool. It is **not affiliated with,
endorsed by, or supported by Roborock**. It talks to your own account over Roborock's cloud and
relies on undocumented internals that the vendor can change at any time. Provided **as-is, with no
warranty — use at your own risk.** Commands here are reversible and the project errs heavily toward
safety (e.g. `clean-rooms --dry-run` posts a *disabled* job), but you are responsible for your
device and account. Don't run it on hardware or an account you can't afford to disrupt.

## Tested hardware

| Item | Tested |
|---|---|
| Model | Roborock Q10 S5+ (`roborock.vacuum.ss07`, B01 protocol) |
| Firmware | **last validated against 03.11.24** (2026-06) |
| Python | 3.11 (3.11+ required) · `python-roborock` 5.14.x |

Other Roborock models are **untested** — they may share the B01 protocol (in which case much of
this should work) or differ. Reports from other models are welcome; see
[CONTRIBUTING.md](CONTRIBUTING.md). When Roborock pushes a firmware update, behavior may drift from
what's documented here.

## Setup

Needs Python **≥3.11** (python-roborock 5.x requires it; on 3.9/3.10 pip silently installs an old
0.x that lacks the B01 device modules) and the deps in `requirements.txt` (`pip install -r requirements.txt`:
python-roborock, lz4, Pillow). For a reproducible install, `requirements.lock.txt` pins the exact
known-good versions. `vac.py` has a `#!/usr/bin/env python3` shebang, so `./vac.py` runs from any
shell once the deps are on that interpreter.

First-time auth (one time):

```bash
./vac.py login --email you@example.com   # emails you a 6-digit code
./vac.py discover                        # fetches + caches your device list
```

`login` saves a token to `~/.roborock_vac.json` (gitignored; see
[`credentials.example.json`](credentials.example.json) for its schema); `discover` caches
device/home data to `~/.roborock_vac_cache.pkl` so later calls don't hit the cloud rate limit.

> **Be gentle with the cloud.** A single MQTT connection is the safe way to use this — many
> separate connections in a short window trip an account-level rate-limit (`code 135`) that
> locks out the CLI *and* the app for a while. That's what the **daemon** (below) is for.

## Daemon (experimental)

The intended way to avoid the rate-limit is a small background **daemon** that holds **one**
persistent cloud connection, so commands don't each open a new MQTT session — and it's the default
path when one is running. **Caveat:** the daemon's persistent-connection behaviour is still being
validated against a live robot, so for now the proven path is one-shot standalone mode (`--force`,
below); use the daemon and fall back to `--force` if it misbehaves. Start it once:

```bash
./vac.py daemon start          # holds one connection; commands route through it
./vac.py daemon start --careful  # stop COMPLETELY on the first 135/auth complaint (safest)
./vac.py daemon status         # device, health, last update, taps
./vac.py daemon stop
./vac.py daemon restart        # e.g. after `pip install -U python-roborock`
```

On trouble the daemon backs off on an escalating schedule and, after repeated failures,
reports `NEEDS LOGIN`. **`--careful`** is stricter: it shuts the daemon down on the *first*
auth/rate-limit complaint (recording why in `~/.roborock_vacd.halt`, shown by `daemon status`)
so it can't possibly extend a ban — recommended while validating against a live robot.

With the daemon running, `./vac.py status`, `clean-rooms`, `watch`, etc. all use it
automatically. If it isn't running, commands print how to start it. To run a **single**
command standalone (its own one-shot session — avoid repeating, it can hit the rate-limit):

```bash
./vac.py status --force        # or --no-daemon
```

**Telemetry taps** (the daemon is the one place that sees the whole stream, so capture lives
there — opt-in, off by default):

```bash
./vac.py daemon record --events ev.jsonl    # every decoded data-point
./vac.py daemon record --novel new.jsonl    # first-seen DP names (catch new behaviors)
./vac.py daemon record --bytes raw.jsonl     # raw frames (incl. binary/map)
./vac.py daemon record --off
```

> Architecture: the daemon reuses python-roborock's `DeviceManager` + the Home Assistant
> integration's coordinator pattern, with a Unix-socket JSON protocol. Full credits in
> [CREDITS.md](CREDITS.md). Live-validation status is tracked in [ROADMAP.md](ROADMAP.md).

## Usage

```bash
./vac.py status        # battery, state, fan, water, mode, clean time/area
./vac.py start         # start cleaning
./vac.py pause
./vac.py resume
./vac.py stop
./vac.py dock          # return to dock
./vac.py dock-empty    # trigger dock auto-empty
./vac.py find          # play a locate beep
./vac.py rooms         # list rooms on the current map (id + name)
./vac.py clean-rooms kitchen study   # clean only those rooms (dry-validated; live run moves the robot)

./vac.py fan turbo               # quiet | balanced | turbo | max | max_plus
./vac.py water high              # off | low | medium | high
./vac.py mode vac_and_mop        # vac_and_mop | vacuum | mop
./vac.py volume 70               # voice volume 0–100
./vac.py child-lock on           # on | off
./vac.py boost on                # auto carpet-boost on | off

./vac.py consumables             # brush/filter/sensor life counters
./vac.py dnd on --start 22:00 --end 08:00
./vac.py dnd off

# Cloud schedules (stored server-side; these use the REST API, not MQTT).
./vac.py schedule list                          # id · time · rooms · fan/water
./vac.py schedule add --time 09:00              # daily full-house clean at 09:00
./vac.py schedule add --time 09:00 --days mon,wed,fri --rooms kitchen study
./vac.py schedule enable <id>                   # enable / disable / delete by id
./vac.py schedule disable <id>
./vac.py schedule delete <id>

# Machine-readable output (status, consumables, discover):
./vac.py status --json | jq .
./vac.py consumables --json

# Stream live telemetry (one persistent MQTT session) until Ctrl-C.
# The robot pushes ~1 update/sec while cleaning; --interval is just a keepalive poll.
./vac.py watch                           # pretty table of the 19 modeled status fields
./vac.py watch --out clean.csv           # also append rows to a CSV for analysis
./vac.py watch --interval 5              # keepalive poll every 5s (default 10)

# Raw capture: EVERY decoded data-point (~44 the robot actually emits, not just 19).
# JSON-per-frame; the right tool for reverse-engineering zone/schedule payloads.
./vac.py watch --raw                     # frame summaries to the terminal
./vac.py watch --raw --out clean.jsonl   # full values, one JSON object per line

# Map: capture live protocol-301 frames and render the floor plan + robot position.
./vac.py map                             # -> map_rooms.png (labeled rooms) [+ map_path.svg if cleaning]
./vac.py map --timeout 60                # wait longer for frames
./vac.py map --out kitchen               # -> kitchen_rooms.png / kitchen_path.svg (custom output prefix)

# Lower-level: byte capture + offline decode (what `map` wraps).
./vac.py watch --bytes --out cap.jsonl   # capture every raw MQTT frame (incl. binary map)
./decode_map.py cap.jsonl                # -> map_path.svg (route+position) + map_rooms.png (labeled rooms)

./vac.py raw STATUS              # send any raw data-point; see DP names below
```

Multiple robots? Add `--device <duid>` (find DUIDs via `./vac.py discover`).

### `raw` — escape hatch

`raw` sends any B01 data-point directly, for features without a dedicated command:

```bash
./vac.py raw VOLUME 50           # set voice volume
./vac.py raw CHILD_LOCK 1        # enable child lock
```

Run `./vac.py raw BADNAME` to print the full list of known data-point names.
Most B01 commands are fire-and-forget (no response body).

## Files

| Path | Purpose |
|---|---|
| `vac.py` | The CLI |
| `decode_map.py` | Decode the live map/path (incl. grid georeference) from a `watch --bytes` capture |
| `check_roborock_api.py` | Canary: verify the `python-roborock` internals this tool relies on are still present (run after upgrades) |
| [CAPABILITIES.md](CAPABILITIES.md) | Every interaction, scoped: can / can't / unknown |
| [DP_DICTIONARY.md](DP_DICTIONARY.md) | What each data-point means + decoded formats |
| [DESIGN_NOTES.md](DESIGN_NOTES.md) | Why it works this way + the reverse-engineering findings |
| [ROADMAP.md](ROADMAP.md) | What works, what's planned, known limitations |
| `credentials.example.json` | Schema of the login file `login` writes to `~/.roborock_vac.json` |
| `~/.roborock_vac.json` · `~/.roborock_vac_cache.pkl` | Login token · cached home-data (gitignored) |

## Known limitations

- **Cloud-only.** No local control for this model (B01 protocol).
- **Map via `vac.py map`.** Renders the room grid → `map_rooms.png` (colour-coded,
  room-name-labeled floor plan). The room grid streams even while docked; the
  cleaning path + live robot position (`map_path.svg`) only stream *during* a clean.
  Path↔grid georeference is solved (`map_overlay.png`); obstacles are cloud-only (not
  in this data). The library doesn't expose any of this natively.
- **Room/segment cleaning via `vac.py clean-rooms`** — reads room IDs + names from the
  map and issues a one-time REST `/jobs` clean for just those rooms. Dry-validated
  (posts an inert, *disabled* job, confirms it in the list, deletes it before it fires);
  the live run drives the robot. See [DESIGN_NOTES.md](DESIGN_NOTES.md).
- **Structured map mutations are read-only.** Virtual walls, no-go/no-mop zones, and
  room split/merge/rename can be decoded but not set from this tool.
- **Some settings are cloud-authoritative** (volume / child-lock / boost / DND) — writes
  may revert; change those in the app. Runtime settings (fan/water/mode) persist.
- **Consumables** show hours used + % remaining (confirmed against the app:
  main 300 h / side 200 h / filter 150 h lifetimes).

## Who this is for

This is a **command-line / scripting** tool for B01 (Q10-class) Roborocks — useful if you want to
drive the vacuum from a terminal, cron, or your own scripts, or you want a documented B01 protocol
reference. **If you use Home Assistant,** check the [HA Roborock integration](https://www.home-assistant.io/integrations/roborock/)
and community components first — they may already cover your model with a GUI; this tool can still
help as a `shell_command` shim or for things the integration doesn't expose.

## Built on / related projects

This is an unofficial CLI+daemon built on others' work — full credits in [CREDITS.md](CREDITS.md):
- [python-roborock](https://github.com/Python-roborock/python-roborock) — the library this depends on.
- [Home Assistant Roborock integration](https://www.home-assistant.io/integrations/roborock/) — the single-connection coordinator pattern the daemon follows.
- [local_roborock_server](https://github.com/Python-roborock/local_roborock_server) / [Valetudo](https://github.com/Hypfer/Valetudo) — if you want a full *local* cloud replacement instead of controlling via Roborock's cloud.
- [XiaomiRobotVacuumProtocol](https://github.com/marcelrv/XiaomiRobotVacuumProtocol), [dustcloud](https://github.com/dgiese/dustcloud) — the protocol-RE lineage.

## Contributing & license

Contributions (especially reports from other Roborock models) are welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md). For validating against a live robot safely, see the **Be gentle
with the cloud** note above and [DESIGN_NOTES.md](DESIGN_NOTES.md). Protocol details live in
[DP_DICTIONARY.md](DP_DICTIONARY.md) and [CAPABILITIES.md](CAPABILITIES.md).

Licensed under the [MIT License](LICENSE).

## Built with AI assistance

This project was developed with the help of AI coding assistants (Anthropic's Claude Opus 4.8 and
Claude Sonnet 4.6) under human direction and supervision — code, reverse-engineering, and docs. A
human reviewed the work and ran every live test against the real device. See [CREDITS.md](CREDITS.md).
