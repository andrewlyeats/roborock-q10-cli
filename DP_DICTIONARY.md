# Data-point dictionary (B01 / Q10 S5+)

> **As of:** 2026-06-19 (SET-path revision + live-validation) · Q10 S5+ (`roborock.vacuum.ss07`), firmware 03.11.24 · `python-roborock` 5.14.2.
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
| `SUSPECTED_THRESHOLD_UP` | — | `[]` | Appears at clean start; value an empty list when no threshold flagged. Threshold-detection related. Likely a list of suspected threshold locations/edges; needs samples with a non-empty value to decode. |
| `CLIFF_RESTRICTED_AREA_UP` | — | `[]` | Appears at clean start; empty list when none. Cliff-sensor "restricted area" reporting (no-go edges the robot detected). Needs a non-empty sample. |
| `ADD_CLEAN_AREA` | — | `"AQAA"` | Appears at the **fault-RECOVERY moment** (right around each transient 501). Base64 → bytes `01 00 00` → a **flag/marker** (robot re-adding clean area after an interruption), NOT a varying counter. |
| `FLOOR_MATERIAL` | — | `[]` | Per-room floor material. **Format already cracked** (CAPABILITIES: `[01][n](room_id, material)`, `YXRoomMaterial` 2=tile/255=other; SET blocked). |

### STATUS detail

**Full table** (`YXDeviceState`; all 14 values observed ✅): `2`=sleeping (low-power doze
after sitting idle off-dock — woke on the next scheduled clean), `3`=idle, `6`=returning_home,
`7`=remote_control_active, `8`=charging, `10`=paused, `12`=error, `22`=emptying_the_bin, `101`=relocating,
`102`=vacuuming, `103`=mopping, `104`=sweep_and_mop (also the ~2 s leaving-dock transition), `105`=transitioning,
`29`=active mapping.

- **Sequences.** A normal start+stop+return cycle: `8→104→101→104→10→3→6→8`.

- **STATUS↔CLEAN_MODE mapping** — the active-clean status is
  **mode-specific** → CLEAN_MODE `1` (vac_and_mop)=`104`, `2` (vacuum)=`102`, `3` (mop)=`103`. The `6`/`101`/`105`
  values are the surrounding returning/relocating/transition states.
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
| `DUST_SETTING` | dpDustSetting | 0 | auto-empty frequency. `YXDeviceDustCollectionFrequency`: **DAILY=0**, INTERVAL_15/30/45/60. Value 0 = daily. **✅ SET live-validated** (: 0→15 stuck + restored). |
| `MOP_STATE` | dpMopState | 1 | mop pad attached/engaged 0/1. 🟡 (name inference; no detach test) |
| `MAP_SAVE_SWITCH` | dpMapSaveSwitch | true | persist map between runs. **⚠ NOT settable via string-key COMMON** (: write to 0 didn't stick — likely cloud-side or needs another form). |
| `MULTI_MAP_SWITCH` | dpMultiMapSwitch | 1, 4 | multi-floor maps. **NOT a simple bool**; `4`=multi-level enabled, off-value/other semantics uncaptured. The value changed when the **app** toggled multi-level; CLI/MQTT set untested, presumed app-managed (same stored-pref bucket). |
| `CLEAN_LINE` | dpCleanLine (78) | 2 | route pattern. `YXCleanLine`: FAST=0, DAILY=1, **FINE=2** ✅. **Settable** via string-key COMMON(101) (— stuck). |
| `BREAKPOINT_CLEAN` | dpBreakpointClean | 0 | resume-after-charge armed 0/1. 🟡 (name inference). **⚠ NOT settable via string-key COMMON** (: write to 1 didn't stick). |
| `VALLEY_POINT_CHARGING` | dpValleyPointCharging | false/true | off-peak charging enabled (bool). 🟡 (semantics inferred from name + the decoded `_DATA_UP` window) |
| `VALLEY_POINT_CHARGING_DATA_UP` | dpValleyPointChargingDataUp | base64 | off-peak charging window — **same 6-byte format as `NOT_DISTURB_DATA`**: `[flag:u8, startH:u8, startM:u8, endH:u8, endM:u8, trail:u8]` (e.g. decodes to 22:00–08:00). Flag byte 0xFC in all observed samples (0x00 may mean disabled, matching NOT_DISTURB_DATA pattern). **Trail byte is `0` OR `1`** (`/BYACAAB`=…01) — DND's is always 0; meaning unknown. CLI: `vac.py read` now renders this + DND windows human-readably via the shared `_decode_time_window` (`test_dnd_window.py`). The 25:00-hour captures are likely transient picker mid-edits (DND encodes overnight as end<start, not +24). ✅ window format · ⬜ flag/trail semantics |
| `LINE_LASER_OBSTACLE_AVOIDANCE` | — | 1 | obstacle avoidance on 0/1. |
| `CARPET_CLEAN_TYPE` | dpCarpetCleanType | 0 | carpet handling mode. **✅ SET live-validated** (: 0→1 stuck + restored — first time varied off `0`). |
| `GROUND_CLEAN` | dpGroundClean | 0 | ⬜ opaque — only the constant `0` seen; no inferable meaning beyond the name. |
| `BACK_TYPE` | dpBackType | 5 | return-to-dock reason. `YXBackType`: IDLE=0, **BACK_DUSTING=4** ✅, **BACK_CHARGING=5** ✅ |
| `CLEAN_TASK_TYPE` | dpCleanTaskType | 1 | `YXDeviceCleanTask`: IDLE=0, **SMART=1** (full auto), ELECTORAL=2 (room select), DIVIDE_AREAS=3, CREATING_MAP=4, PART=5 ✅ |
| `ADD_CLEAN_STATE` | dpAddCleanState | 0 | second-pass / add-clean active. 🟡 (name inference; pairs with `ADD_CLEAN_AREA`) |
| `TIMER_TYPE` | dpTimerType | 1 | schedule kind. 🟡 (name inference; not cross-referenced to a set timer) |
| `AREA_UNIT` | dpAreaUnit | 1 | 1 = m² (vs ft²). ✅ explains m² area. |

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
| `VIRTUAL_WALL_UP` (57) | base64 `[count:u8]` + per wall `(y1,x1,y2,x2)` BE int16 (**~5 mm** units). ⚠ byte order is **(y,x)** not (x,y). e.g. wall (y=-809,x=-834)→(y=-814,x=-1152). `decode_map.py:parse_virtual_walls` reads it; `encode_virtual_walls` is the byte-exact inverse. | ✅ decode confirmed · **SET = write DP `VIRTUAL_WALL` (56)** via string-key COMMON — built + offline byte-validated, **✅ live round-trip VALIDATED** (: `wall add`→read→`wall clear`(`AA==`)→restored via `vac.py wall`) |
| `RESTRICTED_ZONE_UP` | base64 `[0x01][count:u8]` + per zone: `[type:u8][nverts:u8=4]` + 4×`(x,y)` BE int16 + 20B zero-pad = 38 B/zone. **type values:** `0x00`=no-go rect; **`0x02`=no-mop rect**; `0x03`=**user-drawn** door-threshold (thin rotated quad ~70×220mm; ≠ the robot-suspected thresholds in `SUSPECTED_THRESHOLD_UP`/`CLIFF_RESTRICTED_AREA_UP`, which stayed empty in all captures). Zones are in **FIXED 38-B slots**; `load_dp_overlay` uses want_type=`0x02` for no-mop. | ✅ decode confirmed · **SET = write DP `RESTRICTED_ZONE` (54) — ✅ LIVE-validated** (: added a zone via string-key COMMON, read back, restored) (`vac.py zone`; `encode_restricted_zones` round-trips the captured blobs) |
| `ZONED_UP` (59) | base64 **same scheme as `RESTRICTED_ZONE_UP`**: `[0x01][count:u8]` + per zone `[type:u8][nverts:u8=4]` + 4×`(x,y)` BE int16 (**~5 mm**). type=0x01 → cleaning zone. `AQAA`=empty (count=0). | ✅ format confirmed (`parse_restricted_zones` handles both). SET via write DP `ZONED` + string-key COMMON — untested; zone-CLEAN also carries the rect inline in `START_CLEAN` cmd:3. |
| `CARPET_UP` | JSON `{data:[{id, rug_clean_mode, vertexs:[[x,y]×4]}], op:"list"}`; write echoes `{op:"save",result:1}`. coords (x,y) in the JSON (scale unverified — distinct encoding from the binary zone/wall ~5 mm units). | ✅ decode · 🟡 SET untested |
| `FLOOR_MATERIAL` | base64 `[01][n_rooms:u8]` + per room `(room_id:u8, material:u8)`. Material = `YXRoomMaterial`: 0=horiz-floorboard, 1=vert-floorboard, **2=ceramic tile**, **255=other**. | ✅ confirmed |
| `RESET_ROOM_NAME` | base64 `[01][room_id:u8][00][namelen:u8][name…]`. | ✅ decode · 🟡 SET untested |
| `ROOM_SPLIT` / `ROOM_MERGE` | scalar ack (`=1`); the geometry change is in the regenerated grid, not a coord DP. | ✅ observed · 🟡 SET untested |
| `REMOVE_ZONED_UP` | `{op:"save",result:1}` (ack). | ✅ |
| `RESTRICTED_AREA_UP` / `CLIFF_RESTRICTED_AREA_UP` / `SUSPECTED_THRESHOLD_UP` | base64 list (presumed same scheme). | Unused — thresholds went to RESTRICTED_ZONE. 🟡 |
| `CLEAN_RECORD` (52) | `{data:[<underscore-string per clean>], op:...}` — 12 underscore fields per clean (`id·epoch·`**`duration_min`**`·f3·f4·`**`area×1000`**`·t1·water·mode·route·`**`pass`**`·ok`); **format cracked over a 22-record corpus.** The live **`op:list` fetch now WORKS**: `command.send(COMMON, {"52":{"op":"list"}})` (string key) returns 25 records on our own `/m/o/` (live-validated) — the old "app/push-only" verdict was the enum-key envelope. `op:select <id>` returns an ACK only (`result:1`) — the per-clean fields are already in this op:list string; no extra detail observed. **Full field map + worked example → [CLEAN_RECORD detail](#clean_record-detail).** | ✅ format cracked; **✅ live op:list fetch validated (`vac.py history`)** |
| `CLEAN_EXPAND` | dpCleanExpand | `{room_id_list:[ids]}` or `{}` | Robot's **echo of the room selection for the current job** (a report, not a command). Appears at clean start for ELECTORAL task type. e.g. `{"room_id_list":[1]}` = robot is cleaning room 1. `{}` = full-home clean (no selection). ✅ seen in live captures |
| `CUSTOMER_CLEAN` | dpCustomerClean | base64 blob (440–504 B) | **Room directory** — `[count:u8]` + N×47B records, each `[00][room_id:u8][category:u8]…[namelen][name][pad]`. **byte[2] = room category** (`ROOM_CATEGORY` = {1 master_room, 4 living_room, 6 kitchen, 8 toilet, 10 study, 0 unset}; survives renames; the library has **no** room-type enum → uniquely ours), **byte[10] = floor material** (`YXRoomMaterial` 2 tile / 255 other). Already read more reliably from the LZ4 map via `vac.py rooms`. ✅ |
| `ADD_CLEAN_AREA` | dpAddCleanArea | `AQAA` (base64) | "Add clean area" marker. `AQAA` = `[0x01, 0x00, 0x00]` — appears at the fault-RECOVERY moment (around each transient 501), so it reads as a flag, not a varying counter. Exact function ⬜ (see the fuller entry in *Live cleaning state* above). |
| `NOT_DISTURB_DATA` | base64 packed bytes `[flag, startH, startM, endH, endM, ?]` (read). `[0,22,0,8,0,0]` = 22:00–08:00 (an observed sample; the start hour is just the user's DND setting — a later capture read 23:00). (`cmd_dnd` *writes* a JSON dict — write path unconfirmed.) | ✅ read decode |
| `TIMER` | base64; observed minimal `[1,252,0,0]` (no schedule set), `TIMER_TYPE`=1. | 🟡 format unknown — **CONSTANT across every capture**, so NOT offline-decodable; needs an on-device timer set while capturing (or the MITM-gated write path). |
| `MULTI_MAP` (61) | `{op:"list"}` → map list `[{id,name,timestamp}]`; `{op:"update"}`/`{op:"notify"}` on edits. The `0101` grid arrives as protocol-301, NOT here. **op surface CONFIRMED:** `list` / `update`(rename: id+timestamp stable, only name changes) / `select`({id,name}); `delete` inferred (not captured). Map `id` ≈ creation unix-epoch. Multi-level (`MULTI_MAP_SWITCH=4`) **PRESERVES existing maps**. | ✅ **op:list now REPLIES to us** via `command.send(COMMON, {"61":{"op":"list"}})` (string key) — the old "our op-sends get no reply" was the enum-key envelope. `vac.py multimap list` reads it; select/switch deliberately not exposed (re-localizes the robot while parked) |
| `RECENT_CLEAN_RECORD` | bool; `true` = a recent clean exists (distinct from the `CLEAN_RECORD` data list). | ✅ |

### CLEAN_RECORD detail

**Field map** (12 underscore fields, 0-indexed; cracked over a 22-record corpus):
`0:id` (16-char opaque) · `1:epoch` (clean START, unix sec UTC; +TZ=local) · **`2:duration_min`** (ACTIVE-clean minutes — reads below wall-clock on aborted cleans; op:notify; ↔ Q7 `record_use_time`) ·
`3:f3` (~0.55×dur; likely effective/mop minutes, med conf) · `4:f4` (slow device accumulator — **not** duration,
low conf) · **`5:area_m²×1000`** (12053 → 12.05 m²; ÷1000 order-of-mag confirmed **3 ways** (home-floor ceiling + the library's Q7 ÷100 / V1 ÷1e6 unit family both rule out ÷100 and ÷1e6 for our magnitudes), exact constant pending one app-area cross-check) · **`6:t1`** (monotonic accumulator/sequence counter —
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
room grid streams **even while docked**, but the path/position only streams **during an
active clean** (confirmed 2026-06-12):

| sub-type | size | summary (full byte spec → [FRAME_ANATOMY.md](FRAME_ANATOMY.md)) | status |
|---|---|---|---|
| `0x0201` path | ~23KB | 16B header (bytes 8-9 = point count), then BE int16 (x,y) **path-unit** pairs (≈2.5 mm/unit, not true mm); last point = **robot position**, first ≈ dock; decimated (~20 mm vertices) so it's reliable for route/position but cumulative length underestimates true travel → don't derive speed. *(example header `0201000800020000`; bytes 2-7 vary per clean.)* | ✅ decoded |
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
| `USER_PLAN` | 0 | cloud subscription tier. |

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
- **138 = active clean TYPE** ✅ (disambiguated): `0` idle · **`1` = full clean (`cmd:1`)** · **`2` = segment/"electoral"
  clean (`cmd:2`)** — it mirrors the `START_CLEAN` cmd field; persists through pause (state 10), returns to `0` when the
  clean ends. NOT a generic in-progress flag: a `cmd:1` full clean read `138=1` (the `cmd:2` segment read `2`).

- **139 = constant `5`** across idle / active / paused / returning this session — did not vary; semantics
  unknown (possibly a capability or firmware-version constant). Watch for any non-5 value. ⬜

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

**Command-only** (we send them, robot never echoes them — expected): the confirmed action DPs (`START_CLEAN`, `PAUSE`, `STOP`, `START_BACK`, `START_DOCK_TASK`) are detailed in **Action / command DPs** above; the **string-key COMMON write surface** is now **exercised** — `COMMON`, `REMOTE` (drive), `VIRTUAL_WALL`/`RESTRICTED_ZONE` (wall/zone SET), `CLEAN_RECORD`/`MULTI_MAP` (op:list/select). Still unprobed: `RESUME`, `SEEK`, `RESET_*`, `REQUEST*`, `MAP_RESET`, `REMOVE_ZONED`, `ZONED`, `GET_CARPET`, `SELF_IDENTIFYING_CARPET`, `ROOM_MERGE`, `ROOM_SPLIT`, `JUMP_SCAN`, `REQUEST_DPS`.

**Interesting — may appear under specific conditions:**

| DP | code | When it might appear |
|---|---|---|
| `RAG_LIFE` | 23 | Mop rag hours used — may only emit if the optional mop rag accessory is registered with the dock |
| `CLEANING_PROGRESS` | 141 | **Different DP from `CLEAN_PROGRESS`** (code 87). Never emitted — possibly a newer firmware field or triggered only on demand |
| `FLEEING_GOODS` | 142 | Obstacle-avoidance status — may only emit when the robot is actively avoiding an object |
| `TASK_CANCEL_IN_MOTION` | 132 | Fires when a job is cancelled while the robot is mid-move |
| `CREATE_MAP_FINISHED` | 94 | Fires once when a mapping run completes |
| `DEVICE_INFO` | 34 | Full device info blob — request-only |
| `VOICE_PACKAGE` | 35 | Current voice pack info — request-only |
| `HEARTBEAT` | 110 | Keepalive — never echoed on output topic |
| `CARPET_CLEAN_PREFER` | 44 | Carpet mode preference — may not emit until carpet mode is configured |
| `BUTTON_LIGHT_SWITCH` | 77 | Physical button LED toggle |
| `CUSTOM_MODE` | 39 | Per-room custom settings — may require custom mode active |
| `LOG_SWITCH` | 84 | Debug logging toggle |
| `UNIT` | 42 | Unit system (possibly same as AREA_UNIT, or a legacy alias) |
| `VALLEY_POINT_CHARGING_DATA` | 107 | Write-side of VALLEY_POINT_CHARGING_DATA_UP (set the window) |

## Open questions

- **Map units/origin:** ✅ RESOLVED (2026-06-12). Path is in path-units (≈2.5 mm/unit, not true mm);
  grid↔path georeference confirmed at 99.87 % (see FRAME_ANATOMY.md). `map_overlay.png` produced by `decode_map.py`.
- **Zone/wall coord scale — partially open:** ground-truthed the **absolute** zone/wall unit at **~5 mm**
  (the app's 3.3 ft default zone ≈ 200 units). But `decode_map.py:_mm_to_pixel` renders overlays correctly with
  `coord_scale=2` (path-frame-relative; k≈1.98 from two known walls). `2` (path-relative) vs `~5` (absolute mm) does
  **not** cleanly — likely the path frame is itself not true-mm, or the two-wall calibration matched relative
  placement, not absolute size. **The renderer is deliberately UNCHANGED** (it renders correctly); resolving this needs
  a known physical measurement of a drawn wall/zone. CLI `zone`/`wall` coords are robot-native, so it doesn't affect them.
- **`CLEAN_RECORD` t1 field — RESOLVED:** NOT fan level — a **monotonic accumulator / sequence counter**, not a per-clean parameter. Exact unit still open (record-sequence or runtime tick) but it is definitively not a clean attribute. See the corrected `CLEAN_RECORD` row above.
- **`CLEAN_RECORD` f3/f4:** unknown fields at positions 3-4 (field 2 = duration is decoded). Not duration, not area. Possibly room_count and segment_count or obstacle encounter count.
  - ❓ **Reported cross-reference (openHAB roborock binding, `api/dto/GetCleanRecord.java`, source-verified 2026-06-16):** their `Result` DTO declares, **in order**: `begin, end, duration, area, error, complete, start_type, clean_type, finish_reason, dust_collection_status, avoid_count, wash_count, map_flag, cleaned_area, manual_replenish, dirty_replenish, clean_times`. **Caveat — this is the *classic-protocol JSON* DTO, a different SERIALIZATION from our B01 underscore string, so the order will NOT line up positionally.** Use it only as a vocabulary of *candidate meanings* for our still-unknown positions: our `f3` (~0.55×dur) and `f4` (slow accumulator) are plausibly a second time/`finish_reason`/`avoid_count`; our `f6` monotonic accumulator could be `map_flag` or a sequence id. **Verify against our positional decode before promoting any to ✅.** Note their DTO has no explicit `water`/`route`/`pass` ints (which our B01 string carries at f7/f9/f10), confirming the two formats are not a relabel of each other. (openHAB binding — see [CREDITS.md](CREDITS.md).)
- **`CLEANING_PROGRESS` (code 141):** never seen — what triggers it vs `CLEAN_PROGRESS` (87)?
- **`VALLEY_POINT_CHARGING_DATA_UP` flag byte:** 0xFC in all observed samples. Meaning unknown.
- **`AREA_UNIT=0`:** seen once. Presumably ft² but single sample only.
- **`CLEAN_LINE`, `BACK_TYPE`, `CLEAN_TASK_TYPE`, `BREAKPOINT_CLEAN`:** ✅ meanings confirmed from enum; `BACK_TYPE`=5 (BACK_CHARGING) in normal docking, **=4 (BACK_DUSTING)** during the auto-empty cycle on dock return. `CLEAN_TASK_TYPE`=2 = room/segment clean (vs 1=full).
