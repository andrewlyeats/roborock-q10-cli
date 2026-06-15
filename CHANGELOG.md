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

### Added
- **`history --from-capture <file>`** — decode the robot's clean history (date / duration / area / water /
  mode / route / passes / completed) **offline** from a `watch`/`daemon record` capture. The robot
  broadcasts its history (`CLEAN_RECORD` op:list) on the device topic, so a capture taken while the phone
  app opens its History screen contains the full back-catalog. (The *live* op:list pull is app/push-only —
  still WIP.) 12-field format cross-validated against an 18-record corpus; covered by `test_history.py`.

### Fixed
- **Daemon `watch`/stream now works.** The stream handler sent its head through a helper that closed the
  socket after every send (right for one-shot replies, fatal for a stream), so `watch` got the head then
  EOF and exited with zero frames; `--out` was also ignored on the daemon path. Both fixed and covered by
  an offline socket-level regression test (`test_daemon_stream.py`).
- **`daemon restart` preserves `--careful`** (previously dropped it, silently downgrading to normal mode).
- **Disconnected `watch` clients are reaped promptly** (was: only on the next frame, lingering under an
  idle robot).
- **`status` no longer reports benign lifecycle codes as faults.** The device's fault field is overloaded
  (it also carries state codes); known benign codes are suppressed and decoded codes are labelled.

### Known gaps (see [ROADMAP.md](ROADMAP.md))
- Daemon persistent connection is now **validated live** (holds one connection, survives a clean cycle,
  cheap restart) — but **135 cool-down recovery** is still unproven; `--force` one-shot remains the fallback.
- One fault-free complete physical room clean is still pending (a supervised run reached the room but the
  robot trapped on the return and needed a manual reset).
- `history` parser is written, but the live `op:list` **request** path returns nothing yet — pending.

### Notes
- Settings that the cloud re-asserts (volume / child-lock / boost / DND) print a caveat — change those
  in the app to persist.
