# Changelog

Notable changes to this project. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/). Because this tool reverse-engineers an
undocumented cloud protocol and relies on `python-roborock` internals, each release notes the
environment it was **validated against** — check that before trusting it on a newer stack.

## [0.1.3] — 2026-06-22 — autonomy layer (experimental), map origin from the header, live SLAM heading

Same stack (Q10 S5+, firmware **03.11.24**, `python-roborock` **5.14.2** — locked; upstream is now 5.20.x).
Adds an experimental standalone autonomy layer and folds in a round of map/protocol reverse-engineering —
including a **correction to a claim shipped in 0.1.2** (see Corrected).

### Added
- **Autonomy layer (EXPERIMENTAL)** — standalone tooling built on top of `vac.py`'s cloud-MQTT comms, kept
  *out* of the CLI: `pose_extract.py` (live x/y + heading + path-epoch from the `0201` stream),
  `pose_monitor.py` (live-pose cockpit), `nav.py` (heading-aware, frame-agnostic go-to — closed-loop or
  dead-reckon, `--rel`, multi-waypoint `--patrol`, reloc-loss + stuck aborts), `scan.py` (on-demand lidar
  snapshot: heartbeat → decode the raw `0101` grid; no clean, no motion), and `recover.py`
  (lost→remap→recover). See [AUTONOMY.md](AUTONOMY.md). **⚠ `nav`/`recover` MOVE the robot with no
  AI/laser obstacle avoidance (hardware failsafes unverified) — supervise, clear the area, keep away
  from drop-offs.** Enabled by two findings: DP-110 `HEARTBEAT`
  elicits the live 301 stream on demand (no clean, no rig), and the `0201` header carries a live SLAM heading.
- **Offline test suite + planner check shipped** — the pure unit/decode/codec tests and
  `check_nav_planner.py` now ship, so the docs' "validated" rows have runnable evidence.

### Corrected (supersedes 0.1.2)
- **The map origin IS transmitted in the `0101` header** — bytes 11–14 (`x_min`/`y_min`, raw BE; 5 mm
  units = 2 path-units), resolution at 15–16, dock coords at 17–22. 0.1.2 stated the origin was "not
  transmitted / must be auto-fit" — that was **wrong**. `decode_map.py` now reads it from the header
  (`origin_from_header`, `ox = 2·y_min`, `oy = −2·x_min`); auto-fit is demoted to a fallback/cross-check
  (on-floor parity, 29/31 captures). The byte-layout figure (`assets/frame_layout.svg`) was regenerated to match.

### Changed
- **`0201` header fully decoded** — `path_epoch` (2–3), const (4–7), `point_count` (8–9), **`heading_deg`
  (10–11)** — the live firmware SLAM heading the app ignores (drive-mode 1–2° / teleop 8.7° mae; clean-mode
  heading diverges from the path tangent during maneuvering — instantaneous vs accumulated, not a tight
  regime) — const (12–13), points at 14 (`decode_map`'s renderer still reads 16, an empirical sub-pixel wart
  flagged for a refactor; byte 14 is the true start). Retires the old "byte-3 counter" / "unknown tail"
  reads. Added to `frames.ksy` + FRAME_ANATOMY.
- **`0301` / `0401` frames** reclassified from "undecoded" to the same `0101` grid codec (0301 = full-map
  alternate layer; 0401 = per-room sub-grids).
- **Upstream credit** corrected: our Hawk `/jobs` body-signing fix shipped as **PR #852** (5.15.2) and our
  Q10 zone type-2/3 correction via **#850** (5.18.0).
- `TIMER` DP confirmed **vestigial** on the Q10 (scheduling lives entirely in cloud REST `/jobs`).

### Docs
- Reference (FRAME_ANATOMY / PROTOCOL / CAPABILITIES / DP_DICTIONARY / README) brought current and
  cross-checked; `datapoints.json` regenerated (114/114 documented).

## [0.1.2] — 2026-06-19 — write surface unlocked, reliability fixes, and public-docs finalization

Same stack (Q10 S5+, firmware **03.11.24**, `python-roborock` **5.14.x**). This is the largest change since
0.1.1 and supersedes the 0.1.1 finding that stored prefs don't stick from the CLI (below).

### 2026-06-19 (commits `f6ad9b2` · `63184f5` · `da0e19a` · `3c4794f` · `6b08b11` · `fcd183f`)

#### Fixed
- **`status` stale-cache warning** (`f6ad9b2`) — a long-running daemon could silently serve an 88-min-old
  snapshot with no indication the robot was offline. `cmd_status` now checks `_INJECTED_LAST_UPDATE` (set by
  the daemon on connect) and prints a human warning / adds `stale`+`data_age_s` to `--json` when data is
  older than 90 s. Threshold: 90 s (daemon refreshes every ~15–30 s + 30 s keepalive). 9 offline tests
  (`test_status_stale.py`). The standalone `--force` path is unchanged (fetches live each call).
- **`cmd_dnd` rewritten to the captured app wire form** (`63184f5` · `da0e19a` · `3c4794f`) — the old
  implementation was doubly inert: wrong envelope (direct `command.send`, not string-key COMMON) and wrong
  encoding for the schedule window (JSON dict, not the 6-byte base64 blob). Rewritten to send DP 25
  (`NOT_DISTURB` bool master enable) and DP 33 (`NOT_DISTURB_DATA` base64 window) via `_common_set`. New
  codec `_encode/_decode_dnd_window` round-trips both captured samples byte-exact (`test_dnd_window.py`, 5
  offline tests). **Live-validated 2026-06-19** (supervised): DP 25 flipped off→0, on→1, both stuck on
  re-read; DP 33 window `/BYACQAA` (22:00–09:00) read back exactly (2×); DND schedule left at 22:00–09:00.

#### Added
- **`read` time-window rendering** (`6b08b11`) — `vac.py read NOT_DISTURB_DATA` and
  `vac.py read VALLEY_POINT_CHARGING_DATA_UP` now decode the 6-byte blob into a human-readable
  `HH:MM–HH:MM (on/off)` string. Shared decoder `_decode_time_window` (`test_dnd_window.py`).

#### Changed
- **`clean-rooms` purges spent one-time jobs** (`fcd183f`) — fired one-time jobs (those with
  `repeated==False and enabled==False`) accumulate as `✗` clutter; the REST path now best-effort-deletes
  them after each run (`_purge_spent_onetime_jobs`; skipped on `--dry-run`; DELETE errors are logged, never
  fatal). Count surfaced in the success line. Offline-tested (`test_code_quality.py`); live smoke pending.
- **`--timeout`/`--interval` guards** (`fcd183f`) — non-integer or missing values now exit cleanly via
  `_int_arg` (mirrors `_hhmm_arg`) instead of raising `ValueError` or `TypeError`.

### Added
- **`wall` / `zone` commands** — set/clear virtual walls (DP 56) and no-go/no-mop zones (DP 54) over MQTT;
  wall-SET round-trip and zone-SET are live-validated. No robot motion.
- **`multimap list`**, **`read <DP>`**, **`history --record`** commands; **live `history` op:list pull**
  (the back-catalog now fetches directly, no capture needed).

### Changed / overturned
- **Stored settings are settable.** 0.1.1's "writes revert" interpretation was a
  **wrong-wire-format bug**: writes used an enum-member inner key in the COMMON(101) envelope. With the
  **string-key COMMON** form (the shape the app uses), volume/child-lock/boost/DND/dust/route/carpet stick.
  Exceptions that genuinely don't stick: `BREAKPOINT_CLEAN`, `MAP_SAVE_SWITCH`.
- **Walls/zones are no longer "read-only"**, and the **live history pull is no longer "app-only"** — both
  were the same wire-format bug.
- **Manual drive is no longer "app-only".** Same wire-format bug — `vac.py drive` went through the library
  `RemoteTrait` (enum-member inner key); the **string-key COMMON** form drives the robot (live-validated 2026-06-19).
- **Coordinate units corrected** — zone/wall ~5 mm/unit (was "half-mm", 10× off); path ≈2.5 mm/unit; grid ≈50 mm/px.
- **CLEAN_RECORD** decode confirmed (area ÷1000, field 2 = active-clean minutes; mirrors `b01_q7.CleanRecordDetail`).

### Method
- The write surface was unlocked by **running the app in an Android emulator and observing its own traffic** —
  not the network-level MQTT interception once thought necessary.

### Docs
- Reference (CAPABILITIES / DP_DICTIONARY / PROTOCOL / FRAME_ANATOMY / README) brought
  current to the above, verified by adversarial cross-check against the original captures.
- Clarified the two room-clean paths: **`clean-rooms --mqtt`** = instant MQTT segment-clean (no Hawk, each
  room's saved settings); the default REST `/jobs` job is the scheduled / per-param path. Earlier docs
  implied REST `/jobs` was the only way.
- Marked the headless `roborock-vac.service` **experimental** — the unit isn't validated under a live
  `systemd` (the daemon + exit codes it relies on are tested).

## [0.1.1] — 2026-06-18

Live-validation + reference-accuracy work, same stack as 0.1.0 (Q10 S5+,
firmware **03.11.24**, `python-roborock` **5.14.x**): a fast REST status command, plus a broad docs
accuracy/readability pass.

### Added
- **`status --quick`** — fast device status via the REST device-shadow endpoint (`GET /devices/{duid}/shadow`):
  one Hawk-signed GET, **no MQTT session and no daemon needed** (so it can't trip the `135` connection cap).
  Surfaces state / battery / fan / consumable work-times. Note it reads the **legacy v1 dp space**
  (`RoborockStateCode`: `8`=charging agrees, but a cleaning robot reads as v1 `5`/`17`/`18`, not the B01
  `101–105` codes) — distinct from the MQTT `status`. Endpoint validated live. See [CAPABILITIES.md](CAPABILITIES.md).
- **`drive <forward|left|right|stop|exit>`** — manual remote-drive command (B01 `RemoteTrait`). Built,
  but **proven inert on this firmware**: CLI `REMOTE` writes never move the robot or reach `STATUS=7`,
  while the *same* drive from the Roborock app does — manual drive rides the robot's **blocked input
  topic** (the same wall as settings / wall-edit writes). Kept as an honestly-labelled RE artifact; the
  way forward is a MITM of the app's drive frames. See [CAPABILITIES.md](CAPABILITIES.md) (Manual drive).
  *(overturned in 0.1.2 — the string-key COMMON form works)*
- **`raw --common`** — wrap a data-point as `COMMON{DP: value}` (the robot's input channel the library
  uses for `REMOTE`) instead of a bare `command.send(DP, value)`. A write-path probe: it confirmed that
  COMMON-wrapping does **not** land a write the bare send misses (settings and `START_BACK` all stayed put).

### Changed
- **`decode_map.py` reports the robot from the *latest* path frame, not the largest.** On a multi-clean
  capture the biggest frame can be an earlier/larger room, which placed the robot in the wrong room;
  "where is it now" now uses the most-recent frame, while the georeference fit still uses the most-complete
  frame (most points → best registration). `decode_map.py --json` gains a `path_frame_selection` note.

### Findings (live) — docs only
- **The write path is now mapped per-DP across the whole settings surface.** At the time, every *reportable* stored
  preference appeared not to stick from the CLI (MQTT writes ignored, bare or COMMON-wrapped), while runtime
  cleaning params incl. `CLEAN_COUNT` were settable. `CAPABILITIES.md` / `DP_DICTIONARY.md` updated DP-by-DP.
  *(Later overturned — those prefs ARE settable via the string-key COMMON envelope; see [0.1.2].)*
- **`STOP` promoted to validated ✅** — halts an active clean if caught before it commits to docking.
- **Manual drive reclassified to 🔴 app-only** (see Added) *(overturned in 0.1.2 — the string-key COMMON form works)*. The four structured action DPs
  (`TASK_CANCEL_IN_MOTION` / `JUMP_SCAN` / `GROUND_CLEAN` / `BEAK_CLEAN`) and `START_BACK` are no-ops via a
  bare send.
- New observations: `STATUS=2`=sleeping; `FAULT 556`=relocalize-failure (the physical trigger is left as an
  explicit open question); `MULTI_MAP op:list` is readable **passively** (the robot answers the app's list —
  watch while the app opens its map screen); and several structured DPs decoded from live values (`TIMER`,
  `NOT_DISTURB_DATA`, `ADD_CLEAN_AREA`, …).

### Docs
- Accuracy + readability pass across the protocol reference (PROTOCOL / CAPABILITIES / DP_DICTIONARY /
  FRAME_ANATOMY): reconciled cross-doc contradictions, leaned out the public copy,
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

### Known gaps (see [CAPABILITIES.md](CAPABILITIES.md#limitations))
- Daemon persistent connection is now **validated live** (holds one connection, survives a clean cycle,
  cheap restart) — but **135 cool-down recovery** is still unproven; `--force` one-shot remains the fallback.
- One fault-free complete physical room clean is still pending (a supervised run reached the room but the
  robot trapped on the return and needed a manual reset). *(Reframed post-0.1.0: the recurring doorway `501`
  is the apartment's fixed, unchangeable sill — environmental, not a project goal.)*
- `history` parser is written, but the live `op:list` **request** path returns nothing yet — pending.

### Notes
- Settings that the cloud re-asserts (volume / child-lock / boost / DND) print a caveat — change those
  in the app to persist.
