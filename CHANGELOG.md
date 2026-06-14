# Changelog

Notable changes to this project. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/). Because this tool reverse-engineers an
undocumented cloud protocol and relies on `python-roborock` internals, each release notes the
environment it was **validated against** — check that before trusting it on a newer stack.

## [Unreleased]

Initial public release candidate.

### Validated against
- Device: Roborock Q10 S5+ (B01 protocol), firmware **03.11.24**
- Python **3.11** · `python-roborock` **5.14.x** (exact tree in `requirements.lock.txt`)

### Features
- Reads: `status`, `consumables`, `schedule list`, `rooms`; live telemetry via `watch` (+ CSV/JSONL).
- Control: `start` / `pause` / `resume` / `stop` / `dock` / `dock-empty` / `find`; `fan` / `water` / `mode`.
- Room-targeted cleaning via one-time REST `/jobs` (`clean-rooms`), with a `--dry-run` that posts a
  *disabled* job and deletes it (cannot fire).
- Cloud schedules: `list` / `add` / `enable` / `disable` / `delete`.
- Offline map decode + render (`decode_map.py`, `vac.py map`): room grid, cleaning path, georeference.
- Single-connection daemon to avoid the account-level MQTT connection rate-limit (`code 135`).

### Known gaps (see [ROADMAP.md](ROADMAP.md))
- Daemon persistent-connection behaviour is pending live validation; `--force` one-shot is the proven path.
- One fault-free complete physical room clean is still pending.
- `history` parser is written; the live request round-trip is pending.

### Notes
- Settings that the cloud re-asserts (volume / child-lock / boost / DND) print a caveat — change those
  in the app to persist.
