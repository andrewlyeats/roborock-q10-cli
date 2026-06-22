# Data-point dictionary (B01 / Q10 S5+)

> **As of:** 2026-06-22 (SET-path revision + live-validation) · Q10 S5+ (`roborock.vacuum.ss07`), firmware 03.11.24 · `python-roborock` 5.14.2.
> Best-effort/due-diligence as of this date. The readable overview + method live in **[PROTOCOL.md](PROTOCOL.md)**;
> this is the detailed drill-down.

What each data-point (DP) the robot emits **actually means**, built by observing
live runs (first captured 2026-06-12) and cross-referencing `B01_Q10_DP` in the library.

**Confidence key** (standardised across rows):
**✅ Confirmed** (behavioural/round-trip proof, our HW; cite firmware/date) · **🟡 Plausible** (inferred from
structure/naming, no counter-evidence, not independently triggered) · **❓ Reported** (third-party source,
cited, unverified here) · **⬜ Unknown** (seen, opaque). Confirmed rows should carry a firmware
anchor (e.g. `fw 03.11.24`).

> **Migration note (2026-06-16):** earlier rows used a *legacy* `❓` to mean "our own untested
> hypothesis." Under the key above `❓` now means **Reported (third-party)** only, so those legacy
> markers have been reclassified per-row to **🟡** (named/structural inference) or **⬜** (opaque). If you
> see a stray bare `❓` that isn't paired with a cited external source, treat it as 🟡/⬜ pending review.

- **Observed** = value(s) actually seen in the feed (a range, or the constant value).
- **Meaning** = inferred per the confidence key above (some rows also use ⬆/⬇ to note a value's direction).
- The catalog has **114** DPs; the robot spontaneously emits **~66** (counted across all
  sessions). The rest are request/set-only (e.g. `MULTI_MAP`, `GET_CARPET`) or never
  triggered in our captures. See "Never-seen notable DPs" section at the bottom.

## Live cleaning state (changes during a run)

| DP | code | observed | meaning |
|---|---|---|---|
| `STATUS` | dpStatus | 2,3,6,7,8,10,12,22,29,101,102,103,104,105 | device state enum (`YXDeviceState`); all 14 values observed ✅. `2`=sleeping (idle→low-power doze), `8`=charging, `3`=idle, `6`=returning, `12`=error, `22`=emptying-bin, `29`=mapping; the `102/103/104` active-clean states are mode-specific. **Full table, the state sequences, and the openHAB cross-ref → [STATUS detail](#status-detail) below.** |
| `BATTERY` | dpBattery | 58–66 | battery %. ✅ |
| `CLEAN_PROGRESS` | dpCleanProgress | 26–37 | **% of current job complete (0–100)**. ✅ monotonic. Now surfaced in `status`/`watch`. |
| `CLEAN_AREA` | dpCleanArea | 38–50 | **swept** area this run, m² — distance-swept × lane-width, NOT floor footprint (e.g. a 256 m travel path × ~0.2 m lane ≈ 51 m², reported for a clean in an ~18 m² room). Counts overlap + the multiple passes. ✅ |
| `CLEAN_TIME` | dpCleanTime | 3762–5070 | **task clock, seconds**, ticks ~1/sec. ✅ pauses when docked; flatline while mopping = stall signal. |
| `FAULT` | dpFault | 0 | active fault code; 0 = none. **⚠️ OVERLOADED — also carries lifecycle/state codes, so a non-zero FAULT is NOT necessarily an error** ✅ (e.g. `400`=benign "starting clean", `8`=trapped, `501`=cliff-suspended, `556`=robot announced it couldn't locate itself; physical trigger OPEN — relocalize-fail vs a start/end bump — see FAULT detail). Decoded best-effort via the library's `B01Fault`, always with raw-code passthrough. **Full code table, the `B01Fault` caveat, and the openHAB cross-ref → [FAULT detail](#fault-detail) below.** |
| `SUSPECTED_THRESHOLD_UP` | — | `[]` → `[[-172,157]]` | Suspected-threshold list (DP 100). Usually `[]`, but a **non-empty `[[-172,157]]`** WAS observed  — BE int16 (x,y) **path-units** ≈ (−430,+393) mm — confirming it's a list of robot-detected threshold/cliff coordinates in the path frame, as hypothesized. ✅ format now decoded. |
| `CLIFF_RESTRICTED_AREA_UP` | — | `[]` | Appears at clean start; empty list when none. Cliff-sensor "restricted area" reporting (no-go edges the robot detected). Needs a non-empty sample. |
| `ADD_CLEAN_AREA` | — | `"AQAA"` | The **"add a clean area" feature's area data** (the rectangle drawn to add to the current job) — paired with `ADD_CLEAN_STATE`(96). `AQAA`=`01 00 00` is the **empty/default** (no area added). ⚠ our "appears at fault-recovery" read was just this always-present default coinciding with the transient 501s — **not** a fault signal. |
| `FLOOR_MATERIAL` | — | `[]` | Per-room floor material. **Format already cracked** (CAPABILITIES: `[01][n](room_id, material)`, `YXRoomMaterial` 2=tile/255=other; SET blocked). |

### STATUS detail

**Full table** (`YXDeviceState`; **14 of the 18 enum values OBSERVED ✅**; the other 4 are library-known but unobserved here — listed after): `2`=sleeping (low-power doze
after sitting idle off-dock — woke on the next scheduled clean), `3`=idle, `6`=returning_home,
`7`=remote_control_active, `8`=charging, `10`=paused, `12`=error, `22`=emptying_the_bin, `101`=relocating,
`102`=sweeping (library `YXDeviceState.SWEEPING`; = our earlier label "vacuuming"), `103`=mopping, `104`=sweep_and_mop (also the ~2 s leaving-dock transition; **101 reloc + 104 sweep_and_mop LIVE-confirmed 2026-06-22 overnight clean**), `105`=transitioning,
`29`=active mapping. **Library-known but UNOBSERVED here** (completes the `YXDeviceState` enum): `5`=cleaning (a generic
state — we only ever saw the specific `102`/`103`/`104`), `14`=updating (firmware OTA), `99`=saving_map, `108`=waiting_to_charge.


- **Sequences.** A normal start+stop+return cycle: `8→104→101→104→10→3→6→8`.

- **STATUS↔CLEAN_MODE mapping** — the active-clean status is
  **mode-specific** → CLEAN_MODE `1` (vac_and_mop)=`104`, `2` (vacuum)=`102`, `3` (mop)=`103`. The `6`/`101`/`105`
  values are the surrounding returning/relocating/transition states. **CLEAN_MODE `6` (sweep_mop, `YXDeviceWorkMode` only — `YXCleanType` lacks value 6):** the STATUS value while running mode 6 is **not yet observed (OPEN)**. ⚠ Attempting to decode a `CLEAN_TYPE=6` payload via the library's `YXCleanType` enum crashes (value 6 is absent from that enum) — use `YXDeviceWorkMode` instead.
- **`29` = active MAPPING** — a distinct mapping state, not a clean state.

- ⚠️ `6` also appeared during the ACTIVE-clean phase (between undock and dock), which sits oddly with the
  `6=returning_home` label — `6` may be a generic working state; remains an open question.
- ❓ **Reported cross-ref** (openHAB `roborock` binding, `api/enums/StatusType.java`, 2026-06-16): their status enum
  (a *classic Roborock-protocol* table, **not** confirmed to be the B01 `YXDeviceState`) lists
  `3=IDLE, 6=RETURNING, 8=CHARGING, 10=PAUSED, 12=ERROR, 22=EMPTYING_BIN, 29=MAPPING` — **independently corroborating**
  our labels for those codes. It diverges where B01 is its own thing: openHAB `101=OFFLINE` (we observe relocating),
  no `102/104/105` (our mode-specific states; openHAB *does* define `103=LOCKED`, which we never see) — so the 100-range
  is B01-specific. The alignment is the evidence, the divergence is the open edge. (openHAB — see [CREDITS.md](CREDITS.md).)

### FAULT detail

**Decode table = the library's `B01Fault` enum**, which ships in the **Q7** module
(`roborock.data.b01_q7.b01_q7_code_mappings`) — the Q10 module defines `FAULT=("dpFault",90)` but does **not** import
it. `vac.py cmd_status` decodes via `B01Fault[f"F_{code}"]` (imported from `roborock`) and prints the **raw code in
parens when non-zero**; because the table lacks `8`/`400` and remaps others, decoding is best-effort — **keep the raw
passthrough.⚠️ The FAULT DP is OVERLOADED** — it carries normal lifecycle/state codes as well as genuine faults, so a non-zero
FAULT is **not** necessarily an error. Codes seen against a live device:

- **`8` = robot trapped** ✅ This firmware reports trapped as `8`, **not** the library's `513/514 robot_trapped`
  (a firmware remap).
- **`400` = benign "Starting scheduled cleanup"** ✅ a lifecycle/START code, **not** a fault (≈`F_407
  cleaning_in_progress`). Do not present it as an error.
- **`501` = `F_501 robot_suspended`** — cliff-trip/threshold halt mid-clean; a 501 does not necessarily abort.

- **`503` (×1) / `569` (×2)** — observed live but **uncharacterized** (503 during a goto-suite dock cycle; 569 during
  the drain run); neither is in `B01Fault`. 503 sits among the 5xx sensor/localization neighbours; 569 is unlabeled.
  Recorded so they don't age out of the captures; raw-code passthrough surfaces them.
- **`570`** — the table says `F_570 main_brush_entangled`, but that **contradicts** our observation (570 fired on an
  *unreachable* room @ 0 m²; `F_2007/F_2012 cannot_reach_target` fits far better) → **do not trust the 570 label**
  until validated.
- **`556`** — fired when an app **spot-clean** started immediately after a **manual drive**; the robot
  **announced it couldn't determine its location**. Absent from `B01Fault`; sits among the 5xx sensor/localization
  neighbours (`500`=lidar_blocked, `509`=cliff_sensor_error). It self-cleared in ~1 s (`556→0`). **Physical trigger is an OPEN QUESTION** — two live
  hypotheses, not yet separated: (a) a true **relocalization failure** (manual drive left the global pose
  uncertain → the spot-clean relocalize couldn't recover it), or (b) the robot **bumped an object near the
  triangle's start/end point** (the drive began and ended in the same spot, so an obstacle there
  is plausible). **Post-session capture analysis leans (a):** `556` is a *localization* code (not a bumper/trapped
  code `8`/`510`), and manual drive was confirmed to run in a **local odometry frame decoupled from the global
  map** (both app-drives reset to ~`(0,0)` regardless of true global position) — so a failed *global* relocalize
  right after driving is the mechanistic fit. The robot did move ~12 cm during the degraded part-clean, so a
  contributing bump can't be excluded — but the *reported* cause is localization, not collision.

Both `8` and `400` are absent from `B01Fault`. Library neighbours for reference: `500`=lidar_blocked, `509`=cliff_sensor_error,
`510`=bumper_stuck, `513/514`=robot_trapped, `560`=side_brush_entangled, `2007/2012`=cannot_reach_target,
`2102`=cleaning_complete. **Remaining win:** build an empirical code→meaning table (decode live codes via app pushes),
since the q7 table is incomplete and this firmware remaps some codes.

- ❓ **Reported cross-ref** (openHAB `roborock` binding, `api/enums/VacuumErrorType.java`, 2026-06-16): their error
  table (a *classic-protocol* enum, ≠ B01 `B01Fault`) reads **`8 = "Device stuck"`** — **corroborating our
  `FAULT=8 = trapped`** from an independent source (and matching it better than `513/514`). It tops out near
  `56/254/255` and has **none** of our `400`/`501`/`570`, reinforcing those as B01-specific. Neighbours: `4`=Cliff
  sensor fault, `5`=Main brush blocked, `24`=No-go/invisible wall, `28`=Robot on carpet, `254`=Bin full. Treat as a
  labelling cross-check, not B01 ground truth. (openHAB — see [CREDITS.md](CREDITS.md).)

- ❓ **App fault-routing buckets (ss07 device-plugin JS, corpus-RE 2026-06-21; app-side classification — NOT in `B01Fault`, NOT
  yet device-verified except where noted):** the app sorts `dpFault` (90) values into four lists — `D_ErrorCode =
  [1,2,3,4,5,7,8,9,12,14,16,21,24,27,28,29,54,707]` = **hard faults** (drive state=12 + blocking help UI); `D_AlertCode =
  [400,407,500,501,502,503,556,569,570,591]` = **soft alerts** (non-blocking banner — explains why 400/501/556/570 self-clear);
  `D_OfflineCode = [588,589]`; `D_OtherCode = [310,1002,46,58]` (misc — `1002` surfaces the `dpHostError`/112 host sub-code).
  `3001` = a voice-pack-update pseudo-code (not a hardware fault). **So a non-zero FAULT is only a *blocking error* if its code is
  in `D_ErrorCode`.** Full 39-code English title table: the full 39-code English title table (from the device's app i18n). ★ **`501` + `570`
  live-confirmed as soft-alerts this session** (501 on a normal clean completion, 2026-06-22). Treat the rest as ❓ Reported (app-JS)
  until device-confirmed.

## Consumables = HOURS OF USE ✅ (confirmed vs app, 2026-06-12)

| DP | code | observed | meaning |
|---|---|---|---|
| `MAIN_BRUSH_LIFE` | dpMainBrushLife | 6 | **hours of use** ⬆. App % remaining = (300−h)/300 (lifetime 300 h). 6 h → 98%. |
| `SIDE_BRUSH_LIFE` | dpSideBrushLife | 6 | hours used; lifetime **200 h**. 6 h → 97%. |
| `FILTER_LIFE` | dpFilterLife | 6 | hours used; lifetime **150 h**. 6 h → 96%. |
| `SENSOR_LIFE` | dpSensorLife | 6 | hours used; app shows sensor/mop/dust "as needed" (no fixed lifetime → no %). |

> **Confirmed:** the DP value = hours used, matching the app's Settings→Maintenance
> "N h" exactly; % remaining = `(lifetime − hours)/lifetime` with lifetimes
> main 300 h / side 200 h / filter 150 h. `vac.py consumables` now shows "N h · M% left".

## Lifetime totals (constant within a run)

| DP | code | observed | meaning |
|---|---|---|---|
| `TOTAL_CLEAN_AREA` | dpTotalCleanArea | 114→198 | lifetime m² cleaned. ✅ **updates at job end, not mid-run.** |
| `TOTAL_CLEAN_COUNT` | dpTotalCleanCount | 10→11 | lifetime number of cleans. ✅ |
| `TOTAL_CLEAN_TIME` | dpTotalCleanTime | 204→351 | lifetime minutes cleaned. ✅ |
| `CLEAN_COUNT` | dpCleanCount | 2 | passes per area for *this* job (2 = clean-twice), not a room count. ✅ |

## Settings (mirror app toggles; stable unless changed)

> **Writing:** `fan`/`water`/`mode` and runtime params like `CLEAN_COUNT` persist via a direct `command.send`. The
> stored prefs below (`volume`/`child-lock`/`boost`/dust/route/…) need the **string-key COMMON(101)** envelope —
> `command.send(COMMON, {str(code): value})`, the exact form the app uses — and then **STICK** (live-validated:
> set → survives an app re-read → restored). An earlier interpretation found only a *subset* of writes stuck and read
> the rest as server-owned; that was the wrong wire shape (an enum-member inner key), not server authority. CLI `vac.py volume|child-lock|boost` route through string-key COMMON.
> DND (`92`, object) and dust-collection (`50`, enum) are set via their own COMMON payloads — **now CONFIRMED live** — DND `disturb_voice` toggle + `DUST_SETTING` 0→15 both stuck and restored; ⚠ but
> `BREAKPOINT_CLEAN` / `MAP_SAVE_SWITCH` did NOT stick, so the string-key-COMMON SET path is **not universal**.

| DP | code | observed | meaning |
|---|---|---|---|
| `FAN_LEVEL` | dpFanLevel | 8 | suction. 8 = max_plus (`YXFanLevel`). ✅ |
| `WATER_LEVEL` | dpWaterLevel | 3 | mop water. 3 = high (`YXWaterLevel`). ✅ |
| `CLEAN_MODE` | dpCleanMode | 1–4, 6 | clean mode enum. The REST /jobs `cleanMode` param uses `YXCleanType` (1=vac_and_mop, 2=vacuum, 3=mop, 4=customized); the MQTT DP uses `YXDeviceWorkMode` (same codes 1–4, plus 5=save_worry, **6=sweep_mop** — sweep entire flat first, then mop). Codes 1–4 are numerically identical between both enums. **Code 6 observed.** ✅ |
| `VOLUME` | dpVolume (26) | 68 | voice volume 0–100. **✅ SETTABLE** via string-key COMMON(101) — `{"101":{"26":v}}` sticks (no server revert). ✅ |
| `CHILD_LOCK` | dpChildLock | 0 | 0/1. **✅ SETTABLE** via the same string-key COMMON(101) envelope validated on VOLUME. App toggle also confirmed. ✅ |
| `AUTO_BOOST` | dpAutoBoost | 0 | carpet auto-boost 0/1. **✅ SETTABLE** via the same string-key COMMON(101) envelope (the earlier "boost echo stayed 0" was the wrong-envelope artifact, not server authority). App toggle confirmed. ✅ |
| `NOT_DISTURB` | dpNotDisturb (25) | 1 | DND **master enable**, boolean. The app sends it under **string-key COMMON** — `{"101":{"25":true/false}}` — NOT the direct scalar send the old `cmd_dnd` used (the old direct scalar send was the wrong wire shape, like volume/drive). DND is **three** DPs, not one: `25` enable · `33` schedule window · `92` sub-flags. `cmd_dnd` routes `25`/`33` through string-key COMMON. **✅ enable + window SET both live-validated** (2026-06-19: `dnd off`→`25=0` stuck, `dnd on`→`25=1` restored; `dnd on --start 22:00 --end 09:00` → DP 33 read-back = `/BYACQAA`; old direct send was inert). |
| `NOT_DISTURB_DATA` | dpNotDisturbData (33) | base64 | DND **schedule window**, a 6-byte base64 blob `[flag, startH, startM, endH, endM, 0x00]` — flag `0xfc`=on/`0x00`=off. `/BYACAAA`=`fc 16 00 08 00 00`=22:00–08:00 on · `ABcACAAA`=`00 17 00 08 00 00`=23:00–08:00 off. **NOT** the JSON `{enable,startHour,…}` object the old `cmd_dnd` sent. Codec `vac._encode/_decode_dnd_window` round-trips both captured samples byte-exact (`test_dnd_window.py`). **✅ SET live-validated** (2026-06-19: `dnd on --start 22:00 --end 09:00` → read-back returned exactly `/BYACQAA`, 2×). **Reported on CHANGE only** — periodic reads return `null`, so read-back must be timed to the write. |
| `NOT_DISTURB_EXPAND` | dpNotDisturbExpand (92) | dict | DND **sub-flags** object: `{disturb_resume_clean, disturb_voice, disturb_light, disturb_dust_enable}`. **✅ SET live-validated** (: toggled `disturb_voice`, stuck + restored via string-key COMMON). Live read 2026-06-19: `{dust_enable:1, light:0, resume_clean:1, voice:0}`. |
| `DUST_SWITCH` | dpDustSwitch (37) | 1 | auto-empty enabled 0/1. **✅ SETTABLE** via string-key COMMON(101) (— stuck). The "didn't stick (bare + COMMON)" used the enum-key COMMON, not the string key. |
| `DUST_SETTING` | dpDustSetting | 0 | auto-empty frequency. `YXDeviceDustCollectionFrequency`: **`0`=regular** (the app's "regular" — NOT literally "daily"; the installed 5.14.2 mislabels code 0 `DAILY`, #846 renames it to `REGULAR`), `15/30/45/60` = the every-N-cleans "frequent" intervals (app: "regular" vs "frequent"→pick an interval). **✅ SET live-validated** (: 0→15 stuck + restored). |
| `MOP_STATE` | dpMopState | 1 | mop pad attached/engaged 0/1. 🟡 (name inference; no detach test) |
| `MAP_SAVE_SWITCH` | dpMapSaveSwitch | true | persist map between runs. **⚠ NOT settable via string-key COMMON** (: write to 0 didn't stick — likely cloud-side or needs another form). |
| `MULTI_MAP_SWITCH` | dpMultiMapSwitch | 1, 4 | multi-floor maps. **NOT a simple bool**; `4`=multi-level enabled, off-value/other semantics uncaptured. The value changed when the **app** toggled multi-level; CLI/MQTT set untested, presumed app-managed (same stored-pref bucket). |
| `CLEAN_LINE` | dpCleanLine (78) | 2 | route pattern. `YXCleanLine`: FAST=0, DAILY=1, **FINE=2** ✅. **Settable** via string-key COMMON(101) (— stuck). |
| `BREAKPOINT_CLEAN` | dpBreakpointClean | 0 | resume-after-charge armed 0/1. 🟡 (name inference). **⚠ NOT settable via string-key COMMON** (: write to 1 didn't stick). |
| `VALLEY_POINT_CHARGING` | dpValleyPointCharging (105) | false/true | off-peak charging enabled (bool). **SET ✅ live-validated via string-key COMMON** (`false→true→false` round-trip, device-echoed, 2026-06-21). |
| `VALLEY_POINT_CHARGING_DATA_UP` | dpValleyPointChargingDataUp | base64 | off-peak charging window — **same 6-byte format as `NOT_DISTURB_DATA`**: `[tzH:i8, startH:u8, startM:u8, endH:u8, endM:u8, crossMidnight:u8]` (e.g. decodes to 22:00–08:00). **Byte 0 = `tzH`** (device UTC offset, i8): `0xFC` = −4 in our samples — *resolved by the gap-research byte-coverage sweep* (previously read as an opaque flag). **Byte 5 = `crossMidnight`** (0/1): set when the window spans midnight; DND instead encodes overnight as end<start, so its byte 5 stays 0. CLI: `vac.py read` renders this + DND windows human-readably via the shared `_decode_time_window` (`test_dnd_window.py`). The 25:00-hour captures are disabled/sentinel windows (picker mid-edits). ✅ window format + tzH/crossMidnight semantics (gap-research) |
| `LINE_LASER_OBSTACLE_AVOIDANCE` | dpLineLaserObstacleAvoidance (86) | 1 | obstacle avoidance on 0/1. **SET ✅ live-validated via string-key COMMON** (1→0→1 round-trip, device-echoed on the daemon DP capture, 2026-06-21) — another confirmation that the string-key COMMON write path generalizes beyond settings/zones/DND. |
| `CARPET_CLEAN_TYPE` | dpCarpetCleanType | 0 | carpet handling mode — **`YXCarpetCleanType`: `0`=RISE (lift mop + boost over carpet), `1`=AVOID, `2`=IGNORE, `3`=CROSS** *(values from upstream #846's contributor RE, 2026-06-21)*. **✅ SET live-validated** (: our `0→1` = rise→avoid, stuck + restored). |
| `GROUND_CLEAN` | dpGroundClean | 0 | ⬜ opaque — only the constant `0` seen; no inferable meaning beyond the name. |
| `BACK_TYPE` | dpBackType | 5 | return-to-dock reason. `YXBackType`: IDLE=0, **BACK_DUSTING=4** ✅, **BACK_CHARGING=5** ✅ |
| `CLEAN_TASK_TYPE` | dpCleanTaskType | 1 | `YXDeviceCleanTask`: IDLE=0, **SMART=1** (full auto), ELECTORAL=2 (room select), DIVIDE_AREAS=3, CREATING_MAP=4, PART=5 ✅ |
| `ADD_CLEAN_STATE` | dpAddCleanState | 0 | **the app's "add a clean area / re-clean" feature state** — pulses `0→1` while the user draws a rectangle to add an area to the CURRENT clean job. ✅ (supersedes our "second-pass" name-inference) |
| `TIMER_TYPE` | dpTimerType | 1 | schedule kind. 🟡 (name inference; not cross-referenced to a set timer) |
| `AREA_UNIT` | dpAreaUnit | 1 | ✅ **RESOLVED 2026-06-21 — `0`=m², `1`=ft²** (our earlier inferred `1`=m² was BACKWARDS). The **user confirmed the app displays ft²**; `AREA_UNIT` reads `1` across our captures → `1`=ft², matching #846's direct app-toggle RE (`YXAreaUnit`: `0`=square_meter, `1`=square_feet) + the US locale (`"109":"us"`). **Display-preference only** — the `clean_area`/`total_clean_area` status VALUES are natively **m²** (map-cross-checked), so `vac.py`'s `m²` label on them is correct regardless of this DP. |

## Spatial & map-config formats (decoded, read-only over MQTT)

**Provenance:** decoded from a monitored app session (2026-06-12); the **SET path was cracked **.

**`_UP` DPs are device→app *reports*** (e.g. `VIRTUAL_WALL_UP` 57, `RESTRICTED_ZONE_UP` 55) — reading is ✅ confirmed.
**SETTING is now ✅ reachable** via the base DP (no `_UP`) wrapped in the **string-key COMMON(101)** envelope:
`command.send(COMMON, {str(code): blob})`. The long-standing **"🔒 blocked — the write rides an INPUT topic the broker
won't let us subscribe to" theory is OVERTURNED**: the topic was never blocked (replies land on our own
`/m/o/{client-id}`); the real blocker was sending an **enum-member** inner key instead of the **string** code.
**Restricted-zone SET (DP 54) is LIVE-validated** (— added + read back + restored); **virtual-wall SET (DP 56) is
built + offline byte-validated** (encoder round-trips the captured blobs); **wall-SET (DP 56) live round-trip VALIDATED**, zone-SET live-validated . CLI: `vac.py zone` / `vac.py wall`.

**Coordinate frame:** stored zone/wall values are robot units of **~5 mm each (half-cm), NOT half-mm** — ground
truth: the app's default 3.3 ft (≈1006 mm) zone decodes to ~200 units → 5.03 mm/unit (the old "0.5 mm" note was a
half-mm/half-cm slip). Wall binary order is `(y,x)`; zone/carpet coords are `(x,y)`. **Coord-frame reconciliation
(RESOLVED — three frames, not a contradiction):** zone/wall = **5 mm/unit** (absolute) = **2× the path-unit
(~2.5 mm)**, so `decode_map.py:_mm_to_pixel`'s `coord_scale=2` is **CORRECT** (zone-units→path-units, k≈1.98); the grid
pixel is **~50 mm** (`GRID_MM_PER_PIXEL=20` is path-units/px, mislabeled "mm" — the registration `path//20=pixel` holds).
Decisive offline check: grid floor 25,316 px → 10.1 m² @20 mm/px (1.25 m²/room ✗) vs 63 m² @50 mm/px (~8 m²/room ✓). No
renderer change; exact 2.5 mm pending one physical wall/path measurement. For the CLI, `zone`/`wall` coords are
**robot-native — no conversion**. ✅ = decode confirmed, 🟡 = inferred.


| DP | format (decoded) | provenance / confidence |
|---|---|---|
| `VIRTUAL_WALL_UP` (57) | base64 `[count:u8]` + per wall `(y1,x1,y2,x2)` BE int16 (**~5 mm** units). ⚠ byte order is **(y,x)** not (x,y). e.g. real wall blob `Aflu+cX87PoO` = `01 f96e f9c5 fcec fa0e` → (y=-1682,x=-1595)→(y=-788,x=-1522). `decode_map.py:parse_virtual_walls` reads it; `encode_virtual_walls` is the byte-exact inverse. | ✅ decode confirmed · **SET = write DP `VIRTUAL_WALL` (56)** via string-key COMMON — built + offline byte-validated, **✅ live round-trip VALIDATED** (: `wall add`→read→`wall clear`(`AA==`)→restored via `vac.py wall`) |
| `RESTRICTED_ZONE_UP` | base64 `[0x01][count:u8]` + per zone: `[type:u8][nverts:u8=4]` + 4×`(x,y)` BE int16 + 20B zero-pad = 38 B/zone. **type values:** `0x00`=no-go rect; **`0x02`=no-mop rect**; `0x03`=**user-drawn** door-threshold (thin rotated quad ~70×220mm; ≠ the robot-suspected thresholds in `SUSPECTED_THRESHOLD_UP`/`CLIFF_RESTRICTED_AREA_UP`, which were usually empty — though SUSPECTED_THRESHOLD_UP did show a non-empty `[[-172,157]]` in). Zones are in **FIXED 38-B slots**; `load_dp_overlay` uses want_type=`0x02` for no-mop. | ✅ decode confirmed · **SET = write DP `RESTRICTED_ZONE` (54) — ✅ LIVE-validated** (: added a zone via string-key COMMON, read back, restored) (`vac.py zone`; `encode_restricted_zones` round-trips the captured blobs) |
| `ZONED_UP` (59) | base64 **same scheme as `RESTRICTED_ZONE_UP`**: `[0x01][count:u8]` + per zone `[type:u8][nverts:u8=4]` + 4×`(x,y)` BE int16 (**~5 mm**). type=0x01 → cleaning zone. `AQAA`=empty (count=0). | ✅ format confirmed (`parse_restricted_zones` handles both). SET via write DP `ZONED` + string-key COMMON — untested; zone-CLEAN also carries the rect inline in `START_CLEAN` cmd:3. |
| `CARPET_UP` | JSON `{data:[{id, rug_clean_mode, vertexs:[[x,y]×4]}], op:"list"}`; write echoes `{op:"save",result:1}`. **`rug_clean_mode` is very likely `YXCarpetCleanType`** (`0`=rise/`1`=avoid/`2`=ignore/`3`=cross — the per-carpet version of `CARPET_CLEAN_TYPE`; not 100%-confirmed the per-carpet field reuses the enum, but highly plausible). coords (x,y) in the JSON (scale unverified — distinct encoding from the binary zone/wall ~5 mm units). | ✅ decode · 🟡 SET untested |
| `FLOOR_MATERIAL` | base64 `[01][n_rooms:u8]` + per room `(room_id:u8, material:u8)`. Material = `YXRoomMaterial`: 0=horiz-floorboard, 1=vert-floorboard, **2=ceramic tile**, **255=other**. | ✅ confirmed |
| `RESET_ROOM_NAME` | base64 `[01][room_id:u8][00][namelen:u8][name…]`. | ✅ decode · 🟡 SET untested |
| `ROOM_SPLIT` / `ROOM_MERGE` | scalar ack (`=1`); the geometry change is in the regenerated grid, not a coord DP. | ✅ observed · 🟡 SET untested |
| `REMOVE_ZONED_UP` | `{op:"save",result:1}` (ack). | ✅ |
| `RESTRICTED_AREA_UP` / `CLIFF_RESTRICTED_AREA_UP` / `SUSPECTED_THRESHOLD_UP` | base64 list (same scheme). | `RESTRICTED_AREA_UP` + `CLIFF_*` stayed `[]`; **`SUSPECTED_THRESHOLD_UP` had a non-empty `[[-172,157]]`** (— see its row above). User-DRAWN thresholds go to RESTRICTED_ZONE; robot-DETECTED ones surface here. 🟡 |
| `CLEAN_RECORD` (52) | `{data:[<underscore-string per clean>], op:...}` — 12 underscore fields per clean (`id·epoch·`**`duration_min`**`·f3·f4·`**`area×1000`**`·t1·water·mode·route·`**`pass`**`·ok`); **format cracked over a 22-record corpus.** The live **`op:list` fetch now WORKS**: `command.send(COMMON, {"52":{"op":"list"}})` (string key) returns 25 records on our own `/m/o/` (live-validated) — the old "app/push-only" verdict was the enum-key envelope. `op:select <id>` returns an ACK only (`result:1`) — the per-clean fields are already in this op:list string; no extra detail observed. **Full field map + worked example → [CLEAN_RECORD detail](#clean_record-detail).** | ✅ format cracked; **✅ live op:list fetch validated (`vac.py history`)** |
| `CLEAN_EXPAND` | dpCleanExpand | `{room_id_list:[ids]}` or `{}` | Robot's **echo of the room selection for the current job** (a report, not a command). Appears at clean start for ELECTORAL task type. e.g. `{"room_id_list":[1]}` = robot is cleaning room 1. `{}` = full-home clean (no selection). ✅ seen in live captures |
| `CUSTOMER_CLEAN` | dpCustomerClean | base64 blob (440–504 B) | **Room directory** — `[count:u8]` + N×47B records, each `[00][room_id:u8][category:u8]…[namelen][name][pad]`. **byte[2] = room category** (`ROOM_CATEGORY` = {1 master_room, 4 living_room, 6 kitchen, 8 toilet, 10 study, 0 unset}; survives renames; the library has **no** room-type enum → uniquely ours), **byte[10] = floor material** (`YXRoomMaterial` 2 tile / 255 other). The directory (id + name) is read from the LZ4 map via `vac.py rooms`; **byte[2]=category / byte[10]=material are analysis-confirmed positions, NOT surfaced by the tool** (the category enum is this home's, inferred). ✅ |
| `ADD_CLEAN_AREA` | dpAddCleanArea | `AQAA` (base64) | The **"add a clean area" feature's area data** — the rectangle the user draws to add to the current clean job (paired with `ADD_CLEAN_STATE`/96, which pulses 0→1 during the request). `AQAA`=`[0x01,0x00,0x00]` = empty/default (no area added). ✅ Exact function RESOLVED (was ⬜); our "fault-recovery" read was the always-present default coinciding with the 501s, not a fault signal. |
| `NOT_DISTURB_DATA` | base64 packed bytes `[flag, startH, startM, endH, endM, ?]` (read). `[0,22,0,8,0,0]` = 22:00–08:00 (an observed sample; the start hour is just the user's DND setting — a later capture read 23:00). Write: see the canonical **Settings** row above (`NOT_DISTURB_DATA` dpNotDisturbData 33) — ✅ SET live-validated 2026-06-19 via string-key COMMON; NOT a JSON dict. | ✅ read decode · ✅ write (see Settings row) |
| `TIMER` | base64 `AfwAAA==` = `[1,252,0,0]`; `TIMER_TYPE`=1. | ✅ **RESOLVED 2026-06-21 — the on-device `TIMER` DP is VESTIGIAL on the Q10.** It stays `[1,252,0,0]` even with an **active app schedule** (verified live: an app "Scheduled cleaning" for 18:45 Room left `TIMER` unchanged; `REQUEST_TIMER` returns nothing new). **Q10 scheduling lives in the cloud `/jobs`** (cron, decoded by `vac.py schedule`), NOT this DP. So the old "🟡 format unknown / needs a timer set" is closed — setting a timer doesn't touch it; it's minimal/unused. |
| `MULTI_MAP` (61) | `{op:"list"}` → map list `[{id,name,timestamp}]`; `{op:"update"}`/`{op:"notify"}` on edits. The `0101` grid arrives as protocol-301, NOT here. **op surface CONFIRMED:** `list` / `update`(rename: id+timestamp stable, only name changes) / `select`({id}) + **`delete`({id}) — both CONFIRMED live (2026-06-20, string-key COMMON `{"61":{"op":…,"id":…}}`); `delete` frees a slot (map cap ≈ 4). Build a NEW map with `START_CLEAN {"cmd":4}` (quick-map explore, STATUS 29, ~30–60 s) — needs a free slot — then fetch the finalized map via `vac.py map` (onboard cleanup re-segments/re-orients → it ≠ the raw 301 stream frames).** Map `id` ≈ creation unix-epoch. Multi-level (`MULTI_MAP_SWITCH=4`) **PRESERVES existing maps**. | ✅ **op:list now REPLIES to us** via `command.send(COMMON, {"61":{"op":"list"}})` (string key) — the old "our op-sends get no reply" was the enum-key envelope. `vac.py multimap list` reads it; select/switch deliberately not exposed (re-localizes the robot while parked) |
| `RECENT_CLEAN_RECORD` | bool; `true` = a recent clean exists (distinct from the `CLEAN_RECORD` data list). | ✅ |

### CLEAN_RECORD detail

**Field map** (12 underscore fields, 0-indexed; cracked over a 22-record corpus):
`0:id` (16-char opaque) · `1:epoch` (clean START, unix sec UTC; +TZ=local) · **`2:duration_min`** (ACTIVE-clean minutes — reads below wall-clock on aborted cleans; op:notify; ↔ Q7 `record_use_time`) ·
`3:f3` (**secondary clean-time ≈0.6× duration** — 0.55–0.70 over substantive cleans ≥10 min, 34-record re-analysis 2026-06-21; likely the mop/effective-coverage portion of the active duration, med-high conf) · `4:f4` (**NOT an accumulator** — corrected 2026-06-21: per-clean-**distinct** (34/34 unique), **non-monotonic** time-sorted (17/33 vs t1/f6's 30/33); clusters **7224–7960** for most cleans vs **~900** for the short part-cleans; **no dur/area correlation → meaning unresolved**. The ~7400 cluster resembles a 2S Li-ion ~7.4 V in mV, but the ~900 group rules out a pure-voltage read. low conf) · **`5:area_m²×1000`** (12053 → 12.05 m²; ÷1000 order-of-mag confirmed **3 ways** (home-floor ceiling + the library's Q7 ÷100 / V1 ÷1e6 unit family both rule out ÷100 and ÷1e6 for our magnitudes), exact constant pending one app-area cross-check) · **`6:t1`** (monotonic accumulator/sequence counter —
**not** fan level) · `7:water` (YXWaterLevel — 🟡 *mode-correlated*
across 22 records, not write-verified: vacuum→0, vac_mop→{0,1,3,4}, mop→{0,1}; value **`4` exceeds the YXWaterLevel
max (3)** — an unconfirmed possible 4th/custom level) · `8:mode` (YXCleanType; ↔ Q7 `record_clean_mode`) · `9:route` (YXCleanLine; ↔ Q7 `record_clean_way` — 🟡
corpus-inferred) · **`10:pass_count`** (1 or 2; ↔ Q7 `clean_count`) · `11:ok` (1 done / 0 aborted; ↔ Q7 `record_task_status` — really a **status code** {0,1,2}, not a pure boolean). **Sibling:** the field set mirrors the library's named `b01_q7.CleanRecordDetail`; ours is the compact (no map-url) DP-52 variant.

**Worked example.** `…_1781226271_27_19_6692_12053_4_00_02_01_1_1` = started 2026-06-11 21:04, **27 min, 12.05 m²**,
water off, vacuum-only, daily route, 1 pass, completed.

**Fetch — ✅ SOLVED (supersedes the old "not pull-able / needs a :8883 MITM" RE).**
`command.send(COMMON, {"52":{"op":"list"}})` (string-key COMMON — **not** a bare `command.send(CLEAN_RECORD,…)`)
returns the full `data[]` on our own `/m/o/{client-id}` — **25 records, live-validated** (`vac.py history`).
`op:"notify"` = a single live "clean finished" event (coincides with `TOTAL_CLEAN_COUNT`+1);
`op:"select" <id>` returns only an ACK (`result:1`) — **no** extra per-record detail observed (the per-clean
fields are already in the `op:list` string). `vac.py history --record <id>` sends it and dumps the reply.
- **Why every prior verdict was wrong:** the "no reply / push-only / only a transparent :8883 MITM is
  left" attempts used a **bare `command.send(CLEAN_RECORD, {op:list})`** or an **enum-member** COMMON inner key —
  the wire key never rendered to the string `"52"`, so the robot ignored the request. **No topic was ever blocked:**
  the reply lands on the *sender's* `/m/o/`, which the library already subscribes to. The same one root (string-key
  COMMON) also fixed settings-stick + the MULTI_MAP op:list reply.

## Map & position — MQTT protocol 301 (NOT a dps DP)

The robot **spontaneously publishes `map_response` (protocol 301) binary frames** — no
request needed. These are NOT `dps` frames, so `watch`/`watch --raw` never see them (the
dps decoder drops them). Use **`vac.py map`** (one-shot capture + render), or `watch
--bytes` + `decode_map.py` for the raw stream. Two sub-types, keyed by the **first 2 header
bytes** (`0x0101` grid / `0x0201` path) — note they have **different availability**: the
room grid streams **even while docked**; the path/position streams **during an active clean
OR on demand to any client that sends DP-110 (`HEARTBEAT`) polls** — `COMMON(101){"110":1}`
~every 5 s, the app's live-map keepalive. **★ So live pose IS available outside a clean
(2026-06-20) — this broke the long-standing "drive is blind" model;** the 2026-06-12 "only
during a clean" reading simply never sent the heartbeat. Decode raw pose points at byte
**offset 14** (`pose_extract.py`; `decode_map`'s renderer reads offset-16, an empirical sub-pixel wart — byte 14 is the true start, see FRAME_ANATOMY):

| sub-type | size | summary (full byte spec → [FRAME_ANATOMY.md](FRAME_ANATOMY.md)) | status |
|---|---|---|---|
| `0x0201` path | ~23KB | 14B header (byte 14 is the true points start; `decode_map`'s renderer reads offset-16 — an empirical sub-pixel wart, see FRAME_ANATOMY) (bytes 8-9 = point count), then BE int16 (x,y) **path-unit** pairs (≈2.5 mm/unit, not true mm); last point = **robot position**, first ≈ dock; decimated (~20 mm vertices) so it's reliable for route/position but cumulative length underestimates true travel → don't derive speed. *(example header `0201000800020000`; bytes 2-3 = epoch (vary per traversal), 4-7 = const `0x00020000`.)* | ✅ decoded |
| `0x0101` grid | ~7.7KB | LZ4-compressed occupancy grid (`pixel//4=room_id`, 243=outside, 249=wall) + trailing room-name records; W/H read from the header; byte `[6]` = map-finalized flag. **Rendered** by `decode_map.py` → `map_rooms.png` + `map_overlay.png` (colour-coded, labeled, path overlaid). *(our main single-floor map: 222×261 px, 7 named rooms — varies per home; example header `0101<map-id><ver>`, bytes 2-5 = per-map id.)* | ✅ decoded + rendered + georeferenced |

**→ Full byte-level decode is single-sourced in [FRAME_ANATOMY.md](FRAME_ANATOMY.md)** — every offset, the
declared/compressed-size fields, the 47-byte room-record layout, the `raw[11:25]` sub-structure, and the
georeference algorithm + per-install origin (≈99.87 % on-floor fit). Machine-checkable header
schema: [frames.ksy](frames.ksy). *(This dictionary catalogs DPs; the frame format lives there so it has one
home.)*

### Obstacles are NOT in the map data (checked 2026-06-12)
AI-recognized obstacles (cable/shoe/pet icons + photos in the app) are **cloud-side**,
fetched by the app over HTTPS — they never touch the MQTT stream. Verified: no obstacle
301 sub-type; grid pixels are only room/wall(249)/outside(243); the trailing block is the
coverage mask; and the SCMap protobuf (`RobotMap`) has no obstacle/object field at all.
Permanent obstacle *geometry* is baked into the grid as wall cells, but the semantic
layer (type + photo) is cloud-only. Aside: the SCMap `MapHeadInfo` (on-demand RPC only)
carries `resolution` + `minX/maxX/minY/maxY` = clean grid↔mm georeference.

## Identity / environment (constant)

| DP | observed | meaning |
|---|---|---|
| `NET_INFO` | `{ip:192.0.2.x, mac:AA:BB:CC:DD:EE:FF, signal:-48, ssid:<your-ssid>}` (placeholders; real values scrubbed) | wifi info. Control is cloud-only, but the local IP is reachable for presence/ping. |
| `TIME_ZONE` | `America/New_York, -14400s` | device TZ. |
| `OFFLINE` | dpOffline | 0 | online/offline flag; 0 = online. One of the 11 DPs in the REST Shadow endpoint (`GET /devices/{duid}/shadow`) — appears there alongside STATUS/BATTERY/etc. ✅ |
| `ROBOT_COUNTRY_CODE` | `us` | region. |
| `ROBOT_TYPE` | 1 | model class. |
| `VOICE_VERSION` / `VOICE_LANGUAGE` | 4 / 104 | voice pack version / language id. Language codes from `/app/talc/voice-pkg/info`: 1=zh-CN, 2=zh-TW, 3=en, 101=ko, 102=ru, 103=de, **104=es**, 105=fr, 106=it, 108=ja, 109=uk, 110=he, 111=pl, 112=ro, 113=id, 114=th, 115=vi, 116=pt, 117=ms, 118=es-LA. This device has Spanish voice (104). ✅ |
| `USER_PLAN` (207) | 0 | **CEIP enrollment** — User Experience Improvement Program; `0`=not enrolled / `1`=enrolled. ✅ code 207 library-confirmed (`B01_Q10_DP.USER_PLAN`, `dpUserPlan`, an OUTER direct DP); the 0/1 CEIP semantic is app JS-RE 2026-06-21, not yet live-toggled — supersedes the earlier "cloud subscription tier" guess. |

## REST Shadow endpoint — compact status without MQTT

`GET /devices/{duid}/shadow` (Hawk-authenticated, same as /jobs) returns 11 DPs in a
single REST call, no MQTT session needed. Fields (numeric code → name):

| code | DP name | example |
|---|---|---|
| 135 | OFFLINE | 0 |
| 121 | STATUS | 8 |
| 122 | BATTERY | 97 |
| 123 | FAN_LEVEL | 8 |
| 125 | MAIN_BRUSH_LIFE | 6 |
| 126 | SIDE_BRUSH_LIFE | 6 |
| 127 | FILTER_LIFE | 6 |
| 136 | CLEAN_COUNT | 1 |
| 137 | CLEAN_MODE | 1 |
| 138 | CLEAN_TASK_TYPE | 0 |
| 139 | BACK_TYPE | 5 |

Could back a `vac.py status --quick` that skips device_session setup (no MQTT connect,
no waiting for status frames). Subset of what `status` shows but much faster. **`status --quick` BUILT** ✅ — legacy v1 dp space.

**Additional live observations for shadow codes 138 and 139 (2026-06-19):**
- **138 = `CLEAN_TASK_TYPE` (active clean type)** ✅ — the **complete** library `YXDeviceCleanTask` enum: `-1` unknown ·
  `0` IDLE · **`1` SMART (full, `cmd:1`)** · **`2` ELECTORAL (segment, `cmd:2`)** · **`3` DIVIDE_AREAS (zone, `cmd:3`)** ·
  **`4` CREATING_MAP (map-build, `cmd:4`)** · **`5` PART (spot, `cmd:5`)** — it **ends at 5, so our 1–5 cmd catalogue is
  COMPLETE** (no `cmd:6+`). It mirrors the `START_CLEAN` cmd field; persists through pause
  (state 10), returns to `0` when the clean ends. NOT a generic in-progress flag: a `cmd:1` full clean read `138=1` (the
  `cmd:2` segment read `2`; a **`cmd:5` part/spot clean read `138=5` with STATUS `Task=part` — live-verified 2026-06-21**).
  Upstream **#851 (app-captured) independently corroborates** the cmd values (1=whole-home, 2=segment, 5=spot) + the segment
  form `{"cmd":2,"clean_paramters":[ids]}` — the **misspelled `clean_paramters` key matches our capture** (so it's the real
  firmware key). Note **`cmd:4`=`CREATING_MAP` IS in the library `YXDeviceCleanTask` enum** (so the *value* isn't unknown to
  upstream) — but **no #846–851 PR WIRES a map-build command** using it → the map-build *capability* (our `vac.py map-build`)
  is still uniquely ours.

- **139 = `BACK_TYPE` (return/dock state) — RESOLVED, not a mystery constant.** It read `5` constantly only because the
  robot was docked+charging the whole session: **`5` = `BACK_CHARGING`** (`YXBackType` — see the `BACK_TYPE` row). It DOES
  vary — **`4` = `BACK_DUSTING`** during the dock auto-empty (confirmed live), `0` = idle, `-1` = unknown. So the earlier
  "constant 5 / semantics unknown" was a single-state artifact. ✅

## Action / command DPs

The control channel: `command.send(<DP>, <params>)`, fire-and-forget — the robot acts but does NOT echo these as
state (confirm by the resulting STATUS/behaviour). Param shapes differ between python-roborock and openHAB's merged
Q10 code; where they disagree, both are listed and flagged unprobed.

**The two write envelopes (captured from the app's wire):**
- **Top-level** lifecycle verbs — `clean` `{"201":{…}}`, `dock` `{"202":5}`, `pause` `{"204":0}`, `stop` `{"206":0}`:
  sent as `command.send(<DP>, <params>)` directly.
- **COMMON(101) with STRING inner keys** — everything else: queries, settings, zone/wall SET, history, multi-map,
  **manual drive**. Wire shape `{"dps":{"101":{"<code>":value}}}` where `<code>` is the **string** form of the DP
  code (`"26"`, `"52"`, `"54"`, …), **NOT** the enum member. This one detail (string-vs-enum inner key) was the single
  root cause behind three prior dead-ends — settings "cloud-revert", action DPs "inert", history
  "MITM-gated" — all the same wire-format bug. Replies land on the **sender's own** `/m/o/{client-id}`
  (`client-id = md5hex(rriot.u:rriot.k)[2:10]`, which the library already computes + subscribes to) → **no MITM
  needed.**

| DP (code) | params | meaning |
|-----------|--------|---------|
| `START_CLEAN` (201) | `{"cmd":1}` full clean · `{"cmd":2,"clean_paramters":[room_ids]}` room/segment clean | start. ✅ both validated. Room-clean key is the **misspelled** `clean_paramters` as a **bare list** — firmware accepts only that; the robot reports the cmd:2 run as `CLEAN_TASK_TYPE`="electoral". |
| `PAUSE` (204) | library `{}` · openHAB `0` | pause current task. ✅ code; param form unprobed (both may work). |
| `STOP` (206) | library `{}` · openHAB `0` | stop current task. ✅ code; param form unprobed. |
| `START_DOCK_TASK` (203) | `{}` | return to dock — the library's `return_to_dock` path. 🟡 |
| `START_BACK` (202) | `5` | dock/return — **the app docks via top-level `{"202":5}`** (capture confirms openHAB). The 202-vs-203 question is now mostly resolved: the app uses **202:5**; whether 203 (`START_DOCK_TASK`, the library path) also docks is still unprobed. ✅ app path |
| `REMOTE` (101.12) | COMMON string-key `{"101":{"12":v}}` · v = `0` fwd / `2` left (CCW) / `3` right (CW) / `4` stop (release) / `5` exit | **manual remote drive** (moves the robot — use a clear space). App repeat-sends the held direction ~3–4/s and auto-exits remote mode after ~30–40 s idle. **✅ `vac.py drive` live-validated 2026-06-19** (reaches `remote_control_active`, physical rotation; was inert before because `RemoteTrait` sent the enum-member key — same wrong-key bug as settings; fixed in `7c3eb18`). |

**Dock action disambiguation:** `START_BACK` (202) = the app's dock/return path (`{"202":5}`, confirmed by
openHAB); `START_DOCK_TASK` (203) = the library's `return_to_dock` path (`{}`). Both DPs send the robot toward
the dock, but the live A/B distinction (whether 203 also works, or produces different behaviour) is **unprobed** —
an undocked A/B test would settle it. 🟡

Runtime commands that DO carry readable state — `FAN_LEVEL` (123), `WATER_LEVEL` (124), `CLEAN_MODE` (137) — are
MQTT-settable ✅ and live under *Live cleaning state* / *Settings* above.

## Never-seen notable DPs (48 total; most are command/write-only)

DPs in the enum that never appeared in any of our 7 capture files. Grouped by likely reason:

**Command-only** (we send them, robot never echoes them — expected): the confirmed action DPs (`START_CLEAN`, `PAUSE`, `STOP`, `START_BACK`, `START_DOCK_TASK`) are detailed in **Action / command DPs** above; the **string-key COMMON write surface** is now **exercised** — `COMMON`, `REMOTE` (drive), `VIRTUAL_WALL`/`RESTRICTED_ZONE` (wall/zone SET), `CLEAN_RECORD`/`MULTI_MAP` (op:list/select). Still unprobed: `RESUME`, `SEEK`, `RESET_*`, `REQUEST*`, `MAP_RESET`, `REMOVE_ZONED`, `ZONED`, `GET_CARPET`, `SELF_IDENTIFYING_CARPET`, `ROOM_MERGE`, `ROOM_SPLIT`, `JUMP_SCAN`, `REQUEST_DPS`. **Explicit codes (library-vs-dict audit, 2026-06-21 — these completed the 114-DP coverage):** consumable-life resets `RESET_SIDE_BRUSH`(18) `RESET_MAIN_BRUSH`(20) `RESET_FILTER`(22) `RESET_RAG_LIFE`(24) `RESET_SENSOR`(68) — untested by choice (would corrupt maintenance tracking); fetch-requests `REQUEST_TIMER`(69) `REQUEST_NOT_DISTURB_DATA`(75) `CUSTOMER_CLEAN_REQUEST`(63) — pull the timer / DND / room-directory blobs; and `BEAK_CLEAN`(27, name unclear) · `CLEAN_ORDER`(82, likely the room-clean sequence/order) · `IGNORE_OBSTACLE`(89, the inverse toggle of `LINE_LASER_OBSTACLE_AVOIDANCE`). With these, **all 114 enum DPs are now accounted for** in the catalog. **Beyond the enum (updated 2026-06-22):207 is RESOLVED** — it is the library's `USER_PLAN` (`dpUserPlan`, code 207, an OUTER direct DP; CEIP 0/1) — see the `USER_PLAN` row. **112 / 113** are still absent from the installed library (5.14.2); app JS-RE (2026-06-21 corpus) names them **`dpHostError`** (112 — host-MCU error sub-code, surfaces when `FAULT=1002`; app sub-codes `D_HostErrorCode=[1,17,31,104,109,112,129]`) and **`dpFineLogSwitch`** (113 — password-gated verbose-diagnostic upload, a support backdoor). ⚠ Both names are from minified app JS, **NOT library-backed** — needs a live `FAULT=1002` / debug-toggle capture to confirm. PR #846 still suppresses the "112 is not a valid code" warning. **Library-artifact aside:** codes **101** (`COMMON`/`JUMP_SCAN`) and **102** (`REQUEST_DPS`/`CLIFF_RESTRICTED_AREA`) each have two `B01_Q10_DP` members — send/recv namespacing, not a real wire conflict.

**Interesting — may appear under specific conditions:**

| DP | code | When it might appear |
|---|---|---|
| `RAG_LIFE` | 23 | Mop rag hours used — may only emit if the optional mop rag accessory is registered with the dock |
| `CLEANING_PROGRESS` | 141 | **Different DP from `CLEAN_PROGRESS`** (code 87). **Never emitted in any capture — incl. full cleans (gap-research byte-coverage sweep) → vestigial on the Q10** |
| `FLEEING_GOODS` | 142 | Obstacle-avoidance status — may only emit when the robot is actively avoiding an object |
| `TASK_CANCEL_IN_MOTION` | 132 | Fires when a job is cancelled while the robot is mid-move |
| `CREATE_MAP_FINISHED` | 94 | Fires once when a mapping run completes |
| `DEVICE_INFO` | 34 | Full device info blob — request-only |
| `VOICE_PACKAGE` | 35 | Current voice pack info — request-only |
| `HEARTBEAT` | 110 | **Live-map-stream trigger.** The app sends `COMMON(101){"110":1}` ~every 5 s while on its map screen; the robot then streams protocol-301 (live `0101` grid + `0201` path/pose) **+ 102 status to that client — outside a clean too.** Any client that heartbeats gets the live map, **including teleop pose** (`raw --common HEARTBEAT 1` + a bytes tap → `pose_extract.py`). Not echoed on the output topic. |
| `CARPET_CLEAN_PREFER` | 44 | Carpet mode preference — may not emit until carpet mode is configured |
| `BUTTON_LIGHT_SWITCH` | 77 | Physical button LED toggle |
| `CUSTOM_MODE` | 39 | Per-room custom settings — may require custom mode active |
| `LOG_SWITCH` | 84 | Debug logging toggle |
| `UNIT` | 42 | Unit system (possibly same as AREA_UNIT, or a legacy alias) |
| `VALLEY_POINT_CHARGING_DATA` | 107 | Write-side of VALLEY_POINT_CHARGING_DATA_UP (set the window) |

## Open questions

- **Map units/origin:** ✅ RESOLVED (2026-06-12). Path is in path-units (≈2.5 mm/unit, not true mm);
  grid↔path georeference confirmed at 99.87 % (see FRAME_ANATOMY.md). `map_overlay.png` produced by `decode_map.py`.
- **Zone/wall coord scale — ✅ RESOLVED / consistent** (reconciled 2026-06-21; *this entry had gone stale vs the resolved
  body above — fixing that contradiction is the resolution*). The three frames are **mutually consistent:** grid **50 mm/px
  = 20 path-units/px** → path **≈2.5 mm/unit**; zone/wall **≈5 mm/unit = 2× path** (so `coord_scale=2` is correct); anchored
  absolutely by the app's **3.3 ft (1006 mm) default zone ≈ 200 units = 5.03 mm/unit**. The `2` (zone→path **ratio**) and the
  `~5 mm` (zone **absolute**) are different quantities — **not** a contradiction: `5 = 2 × 2.5`. The only residual is that the
  absolute peg rests on ONE app-displayed dimension; an independent physical ruler measurement would *confirm* it but is **not
  needed for consistency**. CLI `zone`/`wall` coords are robot-native regardless. *(The `CARPET_UP` JSON coords are a SEPARATE
  encoding — the 200×200 mm carpet decoded to 200×200 units → ≈**1 mm/unit** if that draw was accurate, distinct from
  zone/path; confirm vs the app's shown carpet size.)*
- **`CLEAN_RECORD` t1 field — RESOLVED:** NOT fan level — a **monotonic accumulator / sequence counter**, not a per-clean parameter. Exact unit still open (record-sequence or runtime tick) but it is definitively not a clean attribute. See the corrected `CLEAN_RECORD` row above.
- **`CLEAN_RECORD` f3/f4 — re-analyzed over 34 records (2026-06-21):f3 = a secondary clean-time ≈0.6× total duration** (0.55–0.70 on substantive cleans → likely the mop/effective-coverage portion of the active minutes; med-high conf). **f4 is NOT an accumulator** (non-monotonic time-sorted, 17/33; only t1/f6 is the accumulator, 30/33): per-clean-distinct (34/34 unique), clusters `7224–7960` for most cleans vs `~900` for short part-cleans, **no dur/area correlation → unresolved** (the ~7400 cluster resembles a 2S Li-ion ~7.4 V in mV, but the ~900 group contradicts that). The old "room_count/segment_count" guess is unsupported.
  - ❓ **Reported cross-reference (openHAB roborock binding, `api/dto/GetCleanRecord.java`, source-verified 2026-06-16):** their `Result` DTO declares, **in order**: `begin, end, duration, area, error, complete, start_type, clean_type, finish_reason, dust_collection_status, avoid_count, wash_count, map_flag, cleaned_area, manual_replenish, dirty_replenish, clean_times`. **Caveat — this is the *classic-protocol JSON* DTO, a different SERIALIZATION from our B01 underscore string, so the order will NOT line up positionally.** Use it only as a vocabulary of *candidate meanings* for our still-unknown positions: our `f3` (~0.55×dur) and `f4` (slow accumulator) are plausibly a second time/`finish_reason`/`avoid_count`; our `f6` monotonic accumulator could be `map_flag` or a sequence id. **Verify against our positional decode before promoting any to ✅.** Note their DTO has no explicit `water`/`route`/`pass` ints (which our B01 string carries at f7/f9/f10), confirming the two formats are not a relabel of each other. (openHAB binding — see [CREDITS.md](CREDITS.md).)
- **`CLEANING_PROGRESS` (code 141):still un-elicited (2026-06-21).** A **part clean (`cmd:5`) drives `CLEAN_PROGRESS` (87)** 0→100%, **not 141** (verified live: 5-min part clean, 87 climbed steadily, zero 141 frames). The **gap-research byte-coverage sweep confirmed 141 is not emitted in ANY capture including full cleans** → an **unused/legacy duplicate enum on this firmware** (vestigial), akin to the opaque 112/113/207. **Resolved — vestigial.** *(Bonus consistency check: the full-status pushes during that clean carried ~30 DPs, ALL cataloged — no unknowns surfaced.)*
- ~~**`VALLEY_POINT_CHARGING_DATA_UP` flag byte:** 0xFC, meaning unknown~~ — **RESOLVED (gap-research):** byte 0 = `tzH` (device UTC offset, i8; `0xFC` = −4), byte 5 = `crossMidnight`. See the `VALLEY_POINT_CHARGING_DATA_UP` row above.
- **`AREA_UNIT` — ✅ RESOLVED 2026-06-21: `0`=m², `1`=ft²** (user confirmed app=ft² while the DP reads its usual `1`; matches #846). The `=0` seen 2026-06-12 was therefore m²-mode. Our earlier inferred `1`=m² is corrected → see the `AREA_UNIT` row.
- **`CLEAN_LINE`, `BACK_TYPE`, `CLEAN_TASK_TYPE`, `BREAKPOINT_CLEAN`:** ✅ meanings confirmed from enum; `BACK_TYPE`=5 (BACK_CHARGING) in normal docking, **=4 (BACK_DUSTING)** during the auto-empty cycle on dock return. `CLEAN_TASK_TYPE`=2 = room/segment clean (vs 1=full).
