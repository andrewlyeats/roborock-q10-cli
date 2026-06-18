# Changelog

Notable changes to this project. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/). Because this tool reverse-engineers an
undocumented cloud protocol and relies on `python-roborock` internals, each release notes the
environment it was **validated against** — check that before trusting it on a newer stack.

## [0.1.1] — 2026-06-18

Live-validation + reference-accuracy work (sessions **s27–s28**), same stack as 0.1.0 (Q10 S5+,
firmware **03.11.24**, `python-roborock` **5.14.x**): a fast REST status command, plus a broad docs
accuracy/readability pass.

### Added
- **`status --quick`** — fast device status via the REST device-shadow endpoint (`GET /devices/{duid}/shadow`):
  one Hawk-signed GET, **no MQTT session and no daemon needed** (so it can't trip the `135` connection cap).
  Surfaces state / battery / fan / consumable work-times. Note it reads the **legacy v1 dp space**
  (`RoborockStateCode`: `8`=charging agrees, but a cleaning robot reads as v1 `5`/`17`/`18`, not the B01
  `101–105` codes) — distinct from the MQTT `status`. Endpoint validated live (s28). See [CAPABILITIES.md](CAPABILITIES.md).
- **`drive <forward|left|right|stop|exit>`** — manual remote-drive command (B01 `RemoteTrait`). Built,
  but **proven inert on this firmware**: CLI `REMOTE` writes never move the robot or reach `STATUS=7`,
  while the *same* drive from the Roborock app does — manual drive rides the robot's **blocked input
  topic** (the same wall as settings / wall-edit writes). Kept as an honestly-labelled RE artifact; the
  way forward is a MITM of the app's drive frames. See [CAPABILITIES.md](CAPABILITIES.md) (Manual drive).
- **`raw --common`** — wrap a data-point as `COMMON{DP: value}` (the robot's input channel the library
  uses for `REMOTE`) instead of a bare `command.send(DP, value)`. A write-path probe: it confirmed that
  COMMON-wrapping does **not** land a write the bare send misses (settings and `START_BACK` all stayed put).

### Changed
- **`decode_map.py` reports the robot from the *latest* path frame, not the largest.** On a multi-clean
  capture the biggest frame can be an earlier/larger room, which placed the robot in the wrong room;
  "where is it now" now uses the most-recent frame, while the georeference fit still uses the most-complete
  frame (most points → best registration). `decode_map.py --json` gains a `path_frame_selection` note.

### Findings (live, s27) — docs only
- **The write path is now mapped per-DP across the whole settings surface.** Every *reportable* stored
  preference is cloud-authoritative (MQTT writes don't stick, bare or COMMON-wrapped), while runtime
  cleaning params incl. `CLEAN_COUNT` are settable. `CAPABILITIES.md` / `DP_DICTIONARY.md` updated DP-by-DP.
- **`STOP` promoted to validated ✅** — halts an active clean if caught before it commits to docking.
- **Manual drive reclassified to 🔴 app-only** (see Added). The four structured action DPs
  (`TASK_CANCEL_IN_MOTION` / `JUMP_SCAN` / `GROUND_CLEAN` / `BEAK_CLEAN`) and `START_BACK` are no-ops via a
  bare send.
- New observations: `STATUS=2`=sleeping; `FAULT 556`=relocalize-failure (the physical trigger is left as an
  explicit open question); `MULTI_MAP op:list` is readable **passively** (the robot answers the app's list —
  watch while the app opens its map screen); and several structured DPs decoded from live values (`TIMER`,
  `NOT_DISTURB_DATA`, `ADD_CLEAN_AREA`, …).

### Docs
- Accuracy + readability pass across the protocol reference (PROTOCOL / CAPABILITIES / DP_DICTIONARY /
  DESIGN_NOTES / FRAME_ANATOMY / ROADMAP): reconciled cross-doc contradictions, leaned out the public copy,
  and sharpened onboarding (clone step + interpreter caveat) and the capability "open frontier" summary.

## [0.1.0] — 2026-06-17

First public release — the reverse-engineering reference + CLI for the Roborock Q10 (B01) cloud protocol.

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
- **Structured output** for scripting / dashboards — `decode_map.py --json` (map + rooms + robot
  position/current-room + georeference), `status` / `consumables --json`, `watch --raw` (JSONL), and a
  machine-readable `datapoints.json` index of every data-point.
- **Installable** — `pip install .` (PEP 621 `pyproject.toml`, enforces Python ≥3.11) with a `vac`
  console command; an optional fail-stop `systemd --user` unit for headless use.

### Added
- **`history --from-capture <file>`** — decode the robot's clean history (date / duration / area / water /
  mode / route / passes / completed) **offline** from a `watch`/`daemon record` capture. The robot
  broadcasts its history (`CLEAN_RECORD` op:list) on the device topic, so a capture taken while the phone
  app opens its History screen contains the full back-catalog. (The *live* op:list pull is app/push-only —
  still WIP.) 12-field format cross-validated against an 18-record corpus; covered by `test_history.py`.
- **Machine-consumable map decode** — `decode_map.py --json` emits grid + georeference, rooms (pixel
  bbox/centroid), the robot's **current position + derived room** (last path point → georeference → grid
  cell → room), and the path as structured data (schema `roborock-b01-map/1`) — so a status panel / web UI /
  Home Assistant shell command can use the decode without parsing a PNG. Covered by `test_decode_map.py`.
- **`datapoints.json`** — a generated, machine-readable index of all 114 B01 data-points + the `YX*` value
  enums (`gen_datapoints.py`; drift-guarded by `test_datapoints.py`). `DP_DICTIONARY.md` stays the reference
  for meanings, confidence tiers, and provenance.
- **Packaging** — a PEP 621 `pyproject.toml` (`pip install .`, `vac` + `roborock-decode-map` scripts) that
  enforces Python ≥3.11, so `pip` refuses the 3.9/3.10 silent-`0.x` downgrade instead of installing a
  B01-less library. `requirements.lock.txt` remains the byte-reproducible pin.
- **Headless daemon support** — a conservative, fail-stop `roborock-vac.service` (`systemd --user`) and
  distinct daemon exit codes (rate-limit `75` / revoked-creds `77` / unreachable `69`) so a service or
  monitor can react; it stops rather than risk the `135` rate-limit (`test_daemon_exit.py`).

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
- **Map decode reads grid dimensions from the frame header** instead of guessing them heuristically, and
  slices the grid by those dimensions — robust to frames that carry a trailing room-record footer (which
  previously mis-sized the grid). Verified header-vs-heuristic agree on every captured frame.
- **No-mop zones now decode.** `RESTRICTED_ZONE_UP` packs zones in fixed-size padded slots; the decoder
  walked them tightly-packed, so with more than one zone it misread a no-go's padding as an empty second
  zone and missed the rest. Now slot-aware, and no-mop zones (type `0x02`) are recognised.

### Known gaps (see [ROADMAP.md](ROADMAP.md))
- Daemon persistent connection is now **validated live** (holds one connection, survives a clean cycle,
  cheap restart) — but **135 cool-down recovery** is still unproven; `--force` one-shot remains the fallback.
- One fault-free complete physical room clean is still pending (a supervised run reached the room but the
  robot trapped on the return and needed a manual reset). *(Reframed post-0.1.0: the recurring doorway `501`
  is the apartment's fixed, unchangeable sill — environmental, not a project goal. See Unreleased.)*
- `history` parser is written, but the live `op:list` **request** path returns nothing yet — pending.

### Notes
- Settings that the cloud re-asserts (volume / child-lock / boost / DND) print a caveat — change those
  in the app to persist.
